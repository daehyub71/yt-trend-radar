# -*- coding: utf-8 -*-
"""core.db — 채널/영상 업서트, 스냅샷 적재, 30일 purge (P1).

purge 는 YouTube ToS 준수 장치다 (SPEC NFR-1) — 배포 직전이 아니라 P1 에서 만든다.
"""
from datetime import datetime, timedelta, timezone

import pytest

from core.config import Settings
from core.db import get_db
from core.models import Channel, ChannelSnapshot, Video, VideoSnapshot

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
CH1 = "UCtest000000000000000001"


@pytest.fixture
def db():
    return get_db(Settings.from_env())


def _channel(cid=CH1, title="하네스푸드", **kw):
    return Channel(id=cid, title=title, subscriber_count=412_000, **kw)


def _video(vid="vidHarness1", published=NOW, **kw):
    return Video(id=vid, channel_id=CH1, title="테스트 영상", published_at=published, **kw)


# ---------------------------------------------------------------- 채널


def test_db_upsert_channels_roundtrip(db):
    assert db.upsert_channels([_channel()]) == 1
    assert db.fetch_channel_ids() == [CH1]


def test_db_upsert_channels_is_idempotent(db):
    db.upsert_channels([_channel()])
    db.upsert_channels([_channel(title="이름변경")])
    assert len(db.fetch_channel_ids()) == 1


def test_db_upsert_channels_empty_is_noop(db):
    assert db.upsert_channels([]) == 0


def test_db_insert_channel_snapshots(db):
    db.upsert_channels([_channel()])
    n = db.insert_channel_snapshots(
        [ChannelSnapshot(channel_id=CH1, ts=NOW, subscriber_count=412_000, view_count=48_200_000)]
    )
    assert n == 1
    assert len(db.fetch_channel_snapshots(CH1)) == 1


def test_db_channel_snapshot_rejects_naive_datetime(db):
    db.upsert_channels([_channel()])
    naive = datetime(2026, 7, 30, 12, 0)  # tz 없음
    with pytest.raises(ValueError, match="naive"):
        db.insert_channel_snapshots([ChannelSnapshot(channel_id=CH1, ts=naive)])


# ---------------------------------------------------------------- 영상


def test_db_upsert_videos_roundtrip(db):
    db.upsert_channels([_channel()])
    assert db.upsert_videos([_video()]) == 1
    assert db.fetch_video_ids() == ["vidHarness1"]


def test_db_insert_video_snapshots(db):
    db.upsert_channels([_channel()])
    db.upsert_videos([_video()])
    n = db.insert_video_snapshots(
        [VideoSnapshot(video_id="vidHarness1", ts=NOW, view_count=152_340)]
    )
    assert n == 1
    assert db.fetch_video_snapshots("vidHarness1")[0]["view_count"] == 152_340


def test_db_insert_video_snapshots_same_ts_is_upsert(db):
    """수집이 중복 실행돼도 (video_id, ts) 는 한 행이다 — PK 가 그렇게 잡혀 있다."""
    db.upsert_channels([_channel()])
    db.upsert_videos([_video()])
    db.insert_video_snapshots([VideoSnapshot(video_id="vidHarness1", ts=NOW, view_count=100)])
    db.insert_video_snapshots([VideoSnapshot(video_id="vidHarness1", ts=NOW, view_count=200)])
    snaps = db.fetch_video_snapshots("vidHarness1")
    assert len(snaps) == 1
    assert snaps[0]["view_count"] == 200


# ---------------------------------------------------------------- purge


def test_db_purge_removes_snapshots_older_than_cutoff(db):
    db.upsert_channels([_channel()])
    db.upsert_videos([_video()])
    old = NOW - timedelta(days=40)
    db.insert_video_snapshots(
        [
            VideoSnapshot(video_id="vidHarness1", ts=old, view_count=10),
            VideoSnapshot(video_id="vidHarness1", ts=NOW, view_count=99),
        ]
    )
    deleted = db.purge_older_than(NOW - timedelta(days=30))
    assert deleted["video_snapshots"] == 1
    remaining = db.fetch_video_snapshots("vidHarness1")
    assert len(remaining) == 1 and remaining[0]["view_count"] == 99


def test_db_purge_removes_videos_by_published_at(db):
    db.upsert_channels([_channel()])
    db.upsert_videos(
        [
            _video("vidOld00000", published=NOW - timedelta(days=45)),
            _video("vidNew00000", published=NOW - timedelta(days=2)),
        ]
    )
    deleted = db.purge_older_than(NOW - timedelta(days=30))
    assert deleted["videos"] == 1
    assert db.fetch_video_ids() == ["vidNew00000"]


def test_db_purge_removes_channel_snapshots(db):
    db.upsert_channels([_channel()])
    db.insert_channel_snapshots(
        [
            ChannelSnapshot(channel_id=CH1, ts=NOW - timedelta(days=31), subscriber_count=1),
            ChannelSnapshot(channel_id=CH1, ts=NOW, subscriber_count=2),
        ]
    )
    deleted = db.purge_older_than(NOW - timedelta(days=30))
    assert deleted["channel_snapshots"] == 1


def test_db_purge_keeps_channels_themselves(db):
    """채널 메타는 30일 규정 대상이 아니다 (계속 갱신되는 추적 대상)."""
    db.upsert_channels([_channel()])
    db.purge_older_than(NOW - timedelta(days=30))
    assert db.fetch_channel_ids() == [CH1]


def test_db_purge_on_empty_db_is_safe(db):
    deleted = db.purge_older_than(NOW - timedelta(days=30))
    assert sum(deleted.values()) == 0


def test_db_purge_requires_tz_aware_cutoff(db):
    with pytest.raises(ValueError, match="naive"):
        db.purge_older_than(datetime(2026, 6, 30, 0, 0))
