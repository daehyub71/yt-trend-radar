# -*- coding: utf-8 -*-
"""실제 YouTube API / RSS 를 호출하는 테스트 — 기본 게이트에서 제외된다.

실행: pytest -m live
쿼터 소모: videos.list 1 + channels.list 1 = 2 units (RSS 는 0)
"""
import pytest

from core.config import Settings
from core.quota import QuotaLedger
from sources.rss_watcher import LiveRssWatcher
from sources.yt_client import LiveYouTubeClient, get_youtube_client

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def live_settings():
    import os

    from dotenv import load_dotenv

    from core.config import PROJECT_ROOT

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    os.environ["YT_MODE"] = "live"
    s = Settings.from_env()
    if not s.yt_api_key:
        pytest.skip("YT_API_KEY 가 필요합니다")
    return s


@pytest.fixture(scope="module")
def popular_video_id(live_settings):
    """mostPopular 로 실재하는 영상 id 하나를 얻는다 (1 unit)."""
    import requests

    r = requests.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={
            "part": "snippet",
            "chart": "mostPopular",
            "regionCode": "KR",
            "maxResults": 1,
            "key": live_settings.yt_api_key,
        },
        timeout=25,
    )
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        pytest.skip("mostPopular 응답이 비어 있음")
    return items[0]["id"], items[0]["snippet"]["channelId"]


def test_yt_client_live_is_live_client(live_settings):
    assert isinstance(get_youtube_client(live_settings), LiveYouTubeClient)


def test_yt_client_live_fetch_video(live_settings, popular_video_id):
    vid, _ = popular_video_id
    client = get_youtube_client(live_settings, quota=QuotaLedger(limit=10))
    got = client.fetch_videos([vid])
    assert len(got) == 1
    v = got[0].video
    assert v.id == vid
    assert v.title
    assert v.published_at.tzinfo is not None
    assert got[0].snapshot.view_count is not None
    assert client.quota.spent == 1, "50개 배치 1회 = 1 unit"


def test_yt_client_live_fetch_channel(live_settings, popular_video_id):
    _, cid = popular_video_id
    client = get_youtube_client(live_settings, quota=QuotaLedger(limit=10))
    got = client.fetch_channels([cid])
    assert len(got) == 1
    ch = got[0].channel
    assert ch.id == cid
    assert ch.uploads_playlist, "uploads 재생목록은 후속 수집에 필요하다"
    assert client.quota.spent == 1


def test_rss_live_fetch_feed_costs_no_quota(popular_video_id):
    """RSS 는 쿼터 0 — 이 프로젝트 수집 전략의 근거다."""
    _, cid = popular_video_id
    feed = LiveRssWatcher().fetch(cid)
    assert feed.channel_id == cid
    assert feed.entries, "공개 채널이면 최소 1개 항목이 있어야 한다"
    assert len(feed.entries) <= 15, "RSS 는 채널당 최신 15개만 노출된다 (실측)"
    e = feed.entries[0]
    assert e.video_id and e.title
    assert e.published_at.tzinfo is not None


def test_rss_live_unknown_channel_returns_empty():
    feed = LiveRssWatcher().fetch("UCthischanneldoesnotexist")
    assert feed.entries == []
