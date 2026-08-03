# -*- coding: utf-8 -*-
"""jobs.collect — 수집 파이프라인 (P4).

파이프라인: 시드 → 채널 통계(배치) → RSS 로 새 영상 감지(쿼터 0) → 영상 통계(배치)
            → 분류 → 스냅샷 적재 → 쿼터 사용량 기록

쿼터 규약이 이 잡의 핵심이다. 하루 3회 도는데 한 번이라도 폭주하면 그날 수집이 죽는다.
"""
from datetime import datetime, timedelta, timezone

import pytest

from core.config import Settings, load_taxonomy
from core.db import get_db
from core.models import Video
from core.quota import QuotaLedger
from jobs.collect import (
    TRACK_DAYS,
    CollectResult,
    classify_video,
    collect,
    select_video_ids,
)
from sources.rss_watcher import get_rss_watcher
from sources.yt_client import get_youtube_client

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
CH1 = "UCtest000000000000000001"
CH2 = "UCtest000000000000000002"


@pytest.fixture
def settings():
    return Settings.from_env()


@pytest.fixture
def tax(config_dir):
    return load_taxonomy(config_dir / "categories.yaml")


def _run(settings, tax, seeds=None, quota=None, now=NOW):
    db = get_db(settings)
    return (
        db,
        collect(
            db=db,
            client=get_youtube_client(settings, quota=quota or QuotaLedger(limit=9_500)),
            watcher=get_rss_watcher(settings),
            taxonomy=tax,
            seeds=seeds if seeds is not None else {"food": [CH1], "tech": [CH2]},
            now=now,
        ),
    )


# ---------------------------------------------------------------- 영상 선정


def test_collect_selects_new_and_tracked_videos():
    """RSS 신규 + 이미 추적 중인 영상 = 이번 회차 조회 대상.

    이미 추적 중인 영상을 계속 다시 찍어야 **2개 이상 스냅샷**이 쌓여 속도를 계산할 수 있다.
    새 영상만 찍으면 영원히 스냅샷 1개짜리만 생긴다.
    """
    tracked = ["vOld0000001"]
    fresh = ["vNew0000001", "vNew0000002"]
    got = select_video_ids(tracked, fresh)
    assert set(got) == {"vOld0000001", "vNew0000001", "vNew0000002"}


def test_collect_select_video_ids_deduplicates():
    got = select_video_ids(["vA00000000"], ["vA00000000", "vB00000000"])
    assert sorted(got) == ["vA00000000", "vB00000000"]


def test_collect_select_video_ids_is_stable():
    """배치 순서가 매번 달라지면 쿼터 사용 패턴을 재현할 수 없다."""
    a = select_video_ids(["v2"], ["v3", "v1"])
    b = select_video_ids(["v2"], ["v3", "v1"])
    assert a == b


# ---------------------------------------------------------------- 분류


def test_collect_classify_video_prefers_title_match(tax):
    v = Video(id="v1", channel_id=CH1, title="제주 흑돼지 맛집 먹방", published_at=NOW)
    assert classify_video(v, channel_category="tech", taxonomy=tax) == "food"


def test_collect_classify_video_falls_back_to_channel_category(tax):
    """제목만으로 못 정하면 채널 카테고리를 쓴다 — 미분류로 버리지 않는다."""
    v = Video(id="v1", channel_id=CH1, title="7월 정산", published_at=NOW)
    assert classify_video(v, channel_category="food", taxonomy=tax) == "food"


def test_collect_classify_video_none_when_no_signal(tax):
    v = Video(id="v1", channel_id=CH1, title="7월 정산", published_at=NOW)
    assert classify_video(v, channel_category=None, taxonomy=tax) is None


# ---------------------------------------------------------------- 파이프라인


def test_collect_upserts_seed_channels(settings, tax):
    db, res = _run(settings, tax)
    assert set(db.fetch_channel_ids()) == {CH1, CH2}
    assert isinstance(res, CollectResult)


def test_collect_assigns_seed_category_to_channel(settings, tax):
    """채널 카테고리의 진실은 seeds.yaml 이다 (검증을 거친 배치이므로)."""
    db, _ = _run(settings, tax)
    ch = {c.id: c for c in db.fetch_all_channels()}
    assert ch[CH1].category_id == "food"
    assert ch[CH2].category_id == "tech"


def test_collect_marks_channels_as_seed(settings, tax):
    db, _ = _run(settings, tax)
    assert all(c.is_seed for c in db.fetch_all_channels())


def test_collect_writes_channel_snapshots(settings, tax):
    db, res = _run(settings, tax)
    assert res.channel_snapshots == 2
    assert len(db.fetch_channel_snapshots(CH1)) == 1


def test_collect_writes_video_snapshots(settings, tax):
    db, res = _run(settings, tax)
    assert res.video_snapshots > 0
    assert db.fetch_video_ids()


def test_collect_snapshots_are_tz_aware(settings, tax):
    db, _ = _run(settings, tax)
    snaps = db.fetch_video_snapshots_since(NOW - timedelta(days=TRACK_DAYS))
    for rows in snaps.values():
        assert all(s.ts.tzinfo is not None for s in rows)


def test_collect_repeated_runs_accumulate_snapshots(settings, tax):
    """같은 영상을 다시 찍으면 스냅샷이 쌓여야 속도를 계산할 수 있다 (핵심)."""
    db = get_db(settings)
    for offset in (2, 0):
        collect(
            db=db,
            client=get_youtube_client(settings, quota=QuotaLedger(limit=9_500)),
            watcher=get_rss_watcher(settings),
            taxonomy=tax,
            seeds={"food": [CH1]},
            now=NOW - timedelta(hours=offset),
        )
    snaps = db.fetch_video_snapshots_since(NOW - timedelta(days=TRACK_DAYS))
    assert any(len(rows) >= 2 for rows in snaps.values())


def test_collect_skips_videos_older_than_track_window(settings, tax):
    """추적 창 밖 영상은 조회하지 않는다 — 쿼터를 아끼고 30일 규정과도 맞는다."""
    db, _ = _run(settings, tax, now=NOW + timedelta(days=TRACK_DAYS + 10))
    assert db.fetch_video_ids() == []


def test_collect_records_quota_usage(settings, tax):
    """쿼터 사용량을 DB 에 남긴다 — 프로세스 간 누적 추적의 근거 (P2 에서 겪은 문제)."""
    db, res = _run(settings, tax)
    assert res.quota_units > 0
    assert res.quota_rows, "ytr_quota_usage 에 적재할 행이 있어야 한다"
    assert all(r["day"] == NOW.date().isoformat() for r in res.quota_rows)


def test_collect_respects_quota_limit(settings, tax):
    """쿼터가 바닥나도 예외로 죽지 않고, 수집한 만큼 저장하고 멈춘다."""
    db, res = _run(settings, tax, quota=QuotaLedger(limit=1))
    assert res.quota_exhausted is True
    assert res.channel_snapshots >= 0  # 죽지 않았다


def test_collect_empty_seeds_is_safe(settings, tax):
    db, res = _run(settings, tax, seeds={})
    assert res.channels == 0
    assert res.quota_units == 0


def test_collect_result_summary_is_printable(settings, tax):
    _, res = _run(settings, tax)
    assert isinstance(res.summary(), str) and res.summary()
