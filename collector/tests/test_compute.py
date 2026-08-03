# -*- coding: utf-8 -*-
"""벌크 조회 + 랭킹 산출 → 게시 경로 (P2, harness DB).

jobs/compute 의 안전 규약을 여기서 못박는다:
  - 스냅샷이 없으면 **기존 랭킹을 지우지 않는다** (빈 보드로 교체하면 서비스가 빈다)
  - 게시는 원자적 전량 교체
"""
from datetime import datetime, timedelta, timezone

import pytest

from core.config import Settings
from core.db import get_db
from core.models import Channel, ChannelSnapshot, Video, VideoSnapshot
from engine.trend_engine import build_boards

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    return get_db(Settings.from_env())


def _seed(db):
    db.upsert_channels(
        [
            Channel(id="UCa", title="큰채널", subscriber_count=500_000, category_id="food"),
            Channel(id="UCb", title="작은채널", subscriber_count=6_000, category_id="food"),
        ]
    )
    db.upsert_videos(
        [
            Video(id="vAAA0000000", channel_id="UCa", title="A영상",
                  published_at=NOW - timedelta(hours=20), category_id="food"),
            Video(id="vBBB0000000", channel_id="UCb", title="B영상",
                  published_at=NOW - timedelta(hours=20), category_id="food"),
            # 보관 구간 밖 — 조회되면 안 된다
            Video(id="vOLD0000000", channel_id="UCa", title="옛날영상",
                  published_at=NOW - timedelta(days=60), category_id="food"),
        ]
    )
    db.insert_video_snapshots(
        [
            VideoSnapshot(video_id="vAAA0000000", ts=NOW - timedelta(hours=10), view_count=100_000),
            VideoSnapshot(video_id="vAAA0000000", ts=NOW - timedelta(hours=2), view_count=300_000),
            VideoSnapshot(video_id="vBBB0000000", ts=NOW - timedelta(hours=10), view_count=5_000),
            VideoSnapshot(video_id="vBBB0000000", ts=NOW - timedelta(hours=2), view_count=45_000),
        ]
    )
    db.insert_channel_snapshots(
        [
            ChannelSnapshot(channel_id="UCa", ts=NOW - timedelta(days=3),
                            subscriber_count=495_000, view_count=80_000_000),
            ChannelSnapshot(channel_id="UCa", ts=NOW, subscriber_count=500_000,
                            view_count=81_000_000),
            ChannelSnapshot(channel_id="UCb", ts=NOW - timedelta(days=3),
                            subscriber_count=4_000, view_count=900_000),
            ChannelSnapshot(channel_id="UCb", ts=NOW, subscriber_count=6_000,
                            view_count=1_100_000),
        ]
    )


# ---------------------------------------------------------------- 벌크 조회


def test_compute_fetch_all_channels(db):
    _seed(db)
    got = {c.id: c for c in db.fetch_all_channels()}
    assert set(got) == {"UCa", "UCb"}
    assert got["UCa"].subscriber_count == 500_000
    assert got["UCa"].category_id == "food"


def test_compute_fetch_videos_respects_cutoff(db):
    _seed(db)
    got = db.fetch_videos_published_since(NOW - timedelta(days=30))
    assert {v.id for v in got} == {"vAAA0000000", "vBBB0000000"}


def test_compute_fetched_video_has_tz_aware_published_at(db):
    _seed(db)
    v = db.fetch_videos_published_since(NOW - timedelta(days=30))[0]
    assert v.published_at.tzinfo is not None


def test_compute_fetch_video_snapshots_grouped(db):
    _seed(db)
    got = db.fetch_video_snapshots_since(NOW - timedelta(days=30))
    assert set(got) == {"vAAA0000000", "vBBB0000000"}
    assert len(got["vAAA0000000"]) == 2
    assert all(s.ts.tzinfo is not None for s in got["vAAA0000000"])


def test_compute_fetch_channel_snapshots_grouped(db):
    _seed(db)
    got = db.fetch_channel_snapshots_since(NOW - timedelta(days=30))
    assert set(got) == {"UCa", "UCb"}


def test_compute_bulk_fetch_rejects_naive_cutoff(db):
    with pytest.raises(ValueError, match="naive"):
        db.fetch_videos_published_since(datetime(2026, 7, 1))


# ------------------------------------------------- PostgREST 쿼리 인코딩 (회귀)
# 실측 2026-08-03: ISO 의 '+00:00' 이 쿼리스트링에서 공백으로 해석돼 PostgREST 가 400 을
# 냈다. purge 도 같은 경로를 쓰므로 ToS 삭제가 조용히 실패할 수 있었다.


def test_db_encode_ts_escapes_plus_sign():
    from core.db import encode_ts

    got = encode_ts(NOW)
    assert "+" not in got, "'+' 가 남으면 공백으로 해석된다"
    assert "%2B" in got
    assert ":" not in got  # 콜론도 인코딩돼야 안전하다


def test_db_encode_ts_rejects_naive():
    from core.db import encode_ts

    with pytest.raises(ValueError, match="naive"):
        encode_ts(datetime(2026, 7, 1))


def test_db_encode_ts_roundtrips():
    from urllib.parse import unquote

    from core.db import encode_ts

    assert datetime.fromisoformat(unquote(encode_ts(NOW))) == NOW


# ---------------------------------------------------------------- 산출→게시


def test_compute_end_to_end_produces_boards(db):
    _seed(db)
    scores = build_boards(
        categories=["food"],
        videos=db.fetch_videos_published_since(NOW - timedelta(days=30)),
        video_snapshots=db.fetch_video_snapshots_since(NOW - timedelta(days=30)),
        channels=db.fetch_all_channels(),
        channel_snapshots=db.fetch_channel_snapshots_since(NOW - timedelta(days=30)),
        now=NOW,
    )
    assert scores
    kinds = {(s.scope, s.kind) for s in scores}
    assert ("video", "trending") in kinds and ("video", "rising") in kinds


def test_compute_rising_and_trending_differ(db):
    """두 보드가 같은 순서면 α 손잡이가 작동하지 않는 것이다."""
    _seed(db)
    scores = build_boards(
        categories=["food"],
        videos=db.fetch_videos_published_since(NOW - timedelta(days=30)),
        video_snapshots=db.fetch_video_snapshots_since(NOW - timedelta(days=30)),
        channels=db.fetch_all_channels(),
        channel_snapshots=db.fetch_channel_snapshots_since(NOW - timedelta(days=30)),
        now=NOW,
    )
    trending = [s.target_id for s in scores if s.scope == "video" and s.kind == "trending"]
    rising = [s.target_id for s in scores if s.scope == "video" and s.kind == "rising"]
    assert trending[0] == "vAAA0000000", "지금 뜨는: 절대 증가량 20만"
    assert rising[0] == "vBBB0000000", "신규 뜨는: 구독자 6천에 4만 증가"


def test_compute_publish_replaces_atomically(db):
    _seed(db)
    db.publish_trend_scores([{"scope": "video", "rank": 1}])
    db.publish_trend_scores([{"scope": "channel", "rank": 1}, {"scope": "channel", "rank": 2}])
    assert len(db.trend_scores) == 2, "이전 보드가 남으면 안 된다 (전량 교체)"


def test_compute_score_rows_are_serializable(db):
    """게시 행은 JSON 으로 나가므로 datetime 이 남아 있으면 안 된다."""
    import json

    _seed(db)
    scores = build_boards(
        categories=["food"],
        videos=db.fetch_videos_published_since(NOW - timedelta(days=30)),
        video_snapshots=db.fetch_video_snapshots_since(NOW - timedelta(days=30)),
        channels=db.fetch_all_channels(),
        channel_snapshots=db.fetch_channel_snapshots_since(NOW - timedelta(days=30)),
        now=NOW,
    )
    json.dumps([s.to_row() for s in scores])  # 예외 없이 통과해야 한다


def test_compute_empty_db_produces_no_scores(db):
    scores = build_boards(
        categories=["food"], videos=[], video_snapshots={},
        channels=[], channel_snapshots={}, now=NOW,
    )
    assert scores == []
