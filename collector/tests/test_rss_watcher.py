# -*- coding: utf-8 -*-
"""sources.rss_watcher — 채널 RSS 감시 (P1).

RSS 는 쿼터를 소모하지 않는다 (PLAN §1). 새 영상 감지의 기본 수단이다.
"""
import pytest

from core.config import Settings
from sources.rss_watcher import HarnessRssWatcher, LiveRssWatcher, get_rss_watcher, parse_feed

CH1 = "UCtest000000000000000001"


@pytest.fixture
def watcher():
    return get_rss_watcher(Settings.from_env())


@pytest.fixture
def feed_xml(request):
    from pathlib import Path

    p = Path(__file__).parent / "fixtures" / f"feed_{CH1}.xml"
    return p.read_text(encoding="utf-8")


def test_rss_watcher_factory_harness(watcher):
    assert isinstance(watcher, HarnessRssWatcher)


def test_rss_watcher_factory_live_needs_no_key(monkeypatch):
    """RSS 는 API 키가 필요 없다 — YT_MODE=live 라도 키 없이 동작해야 한다."""
    monkeypatch.setenv("YT_MODE", "live")
    assert isinstance(get_rss_watcher(Settings.from_env()), LiveRssWatcher)


def test_rss_watcher_parses_channel_identity(feed_xml):
    feed = parse_feed(feed_xml)
    assert feed.channel_id == CH1
    assert feed.channel_title == "하네스푸드"


def test_rss_watcher_restores_stripped_uc_prefix(feed_xml):
    """실측 quirk 회귀 테스트: 루트 <yt:channelId> 는 UC 접두어가 잘려 나온다.

    그대로 믿으면 DB 외래키가 어긋난다 — entry 레벨/링크에서 복원해야 한다.
    """
    assert "<yt:channelId>test000000000000000001</yt:channelId>" in feed_xml
    assert parse_feed(feed_xml).channel_id == "UCtest000000000000000001"


def test_rss_watcher_restores_channel_id_without_entries():
    """항목이 없는 피드는 링크에서 복원해야 한다 (entry 폴백 불가)."""
    from pathlib import Path

    xml = (Path(__file__).parent / "fixtures" / "feed_empty.xml").read_text(encoding="utf-8")
    assert parse_feed(xml).channel_id == "UCtest000000000000000009"


def test_rss_watcher_parses_entries_in_order(feed_xml):
    feed = parse_feed(feed_xml)
    assert [e.video_id for e in feed.entries] == ["vidHarness2", "vidHarness1"]


def test_rss_watcher_entry_fields(feed_xml):
    e = parse_feed(feed_xml).entries[0]
    assert e.video_id == "vidHarness2"
    assert "다낭" in e.title
    assert e.published_at.tzinfo is not None, "tz-aware 여야 한다"
    assert e.thumbnail_url.endswith("hqdefault.jpg")
    assert e.view_count == 988_100


def test_rss_watcher_handles_missing_statistics():
    """media:community 가 없는 피드도 파싱돼야 한다 (조회수는 None)."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
  <yt:channelId>UCtest000000000000000003</yt:channelId>
  <title>통계없는채널</title>
  <entry>
    <yt:videoId>vidNoStats1</yt:videoId>
    <yt:channelId>UCtest000000000000000003</yt:channelId>
    <title>통계 없는 영상</title>
    <published>2026-07-30T00:00:00+00:00</published>
  </entry>
</feed>"""
    e = parse_feed(xml).entries[0]
    assert e.video_id == "vidNoStats1"
    assert e.view_count is None
    assert e.thumbnail_url is None


def test_rss_watcher_handles_empty_feed():
    from pathlib import Path

    xml = (Path(__file__).parent / "fixtures" / "feed_empty.xml").read_text(encoding="utf-8")
    feed = parse_feed(xml)
    assert feed.channel_id == "UCtest000000000000000009"
    assert feed.entries == []


def test_rss_watcher_fetch_returns_feed(watcher):
    feed = watcher.fetch(CH1)
    assert feed.channel_id == CH1
    assert len(feed.entries) == 2


def test_rss_watcher_fetch_unknown_channel_returns_empty(watcher):
    feed = watcher.fetch("UCtest000000000000000404")
    assert feed.entries == []


def test_rss_watcher_new_since_filters_by_time(watcher):
    from datetime import datetime, timezone

    cutoff = datetime(2026, 7, 29, 0, 0, tzinfo=timezone.utc)
    fresh = watcher.new_since(CH1, cutoff)
    assert [e.video_id for e in fresh] == ["vidHarness2"]


def test_rss_watcher_costs_no_quota(watcher):
    """RSS 는 쿼터를 쓰지 않는다 — 이 사실이 설계의 근거이므로 테스트로 못박는다."""
    assert not hasattr(watcher, "quota") or watcher.quota is None
