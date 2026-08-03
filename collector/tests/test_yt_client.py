# -*- coding: utf-8 -*-
"""sources.yt_client — YouTube Data API 래퍼 (P1).

기본 게이트는 harness 구현만 사용한다 (fixtures/ 의 저장된 응답).
"""
import pytest

from core.config import Settings
from core.quota import QuotaExceeded, QuotaLedger
from sources.yt_client import (
    HarnessYouTubeClient,
    LiveYouTubeClient,
    get_youtube_client,
    parse_duration,
)


@pytest.fixture
def client():
    return get_youtube_client(Settings.from_env())


# ---------------------------------------------------------------- 팩토리


def test_yt_client_factory_returns_harness_in_harness_mode(client):
    assert isinstance(client, HarnessYouTubeClient)


def test_yt_client_factory_live_requires_key(monkeypatch):
    monkeypatch.setenv("YT_MODE", "live")
    with pytest.raises(ValueError, match="YT_API_KEY"):
        get_youtube_client(Settings.from_env())


def test_yt_client_factory_live_with_key(monkeypatch):
    monkeypatch.setenv("YT_MODE", "live")
    monkeypatch.setenv("YT_API_KEY", "dummy-key-for-construction-only")
    assert isinstance(get_youtube_client(Settings.from_env()), LiveYouTubeClient)


# ---------------------------------------------------------------- duration


@pytest.mark.parametrize(
    "iso,seconds",
    [
        ("PT45S", 45),
        ("PT12M34S", 754),
        ("PT1H2M3S", 3723),
        ("PT2M", 120),
        ("PT1H", 3600),
        ("P1DT30S", 86_430),
    ],
)
def test_yt_client_parse_duration(iso, seconds):
    assert parse_duration(iso) == seconds


def test_yt_client_parse_duration_invalid_returns_none():
    assert parse_duration("") is None
    assert parse_duration("garbage") is None


# ---------------------------------------------------------------- videos


def test_yt_client_fetch_videos_parses_metadata(client):
    got = client.fetch_videos(["vidHarness1"])
    assert len(got) == 1
    v = got[0].video
    assert v.id == "vidHarness1"
    assert v.channel_id == "UCtest000000000000000001"
    assert "제주" in v.title
    assert v.duration_seconds == 754
    assert v.is_short is False
    assert v.published_at.tzinfo is not None, "tz-aware 여야 한다"
    assert v.thumbnail_url and v.thumbnail_url.startswith("https://")


def test_yt_client_fetch_videos_parses_snapshot(client):
    got = client.fetch_videos(["vidHarness1"])
    s = got[0].snapshot
    assert s.video_id == "vidHarness1"
    assert s.view_count == 152_340
    assert s.like_count == 8_210
    assert s.comment_count == 412
    assert s.ts.tzinfo is not None


def test_yt_client_fetch_videos_marks_short(client):
    got = {f.video.id: f.video for f in client.fetch_videos(["vidHarness1", "vidHarness2"])}
    assert got["vidHarness2"].is_short is True, "45초 영상은 short"
    assert got["vidHarness1"].is_short is False


def test_yt_client_fetch_videos_ignores_unknown_ids(client):
    got = client.fetch_videos(["vidHarness1", "존재하지않음"])
    assert [f.video.id for f in got] == ["vidHarness1"]


def test_yt_client_fetch_videos_empty_input_costs_nothing(client):
    assert client.fetch_videos([]) == []
    assert client.quota.spent == 0


def test_yt_client_fetch_videos_missing_statistics_is_tolerated(client):
    """일부 영상은 좋아요/댓글 수가 비공개다 — None 이어야 하고 예외는 안 된다."""
    got = client.fetch_videos(["vidHarness3"])
    assert got[0].snapshot.comment_count is None
    assert got[0].snapshot.like_count == 2_210


# ---------------------------------------------------------------- channels


def test_yt_client_fetch_channels_parses_metadata(client):
    got = client.fetch_channels(["UCtest000000000000000001"])
    ch = got[0].channel
    assert ch.title == "하네스푸드"
    assert ch.handle == "@harnessfood"
    assert ch.country == "KR"
    assert ch.uploads_playlist == "UUtest000000000000000001"
    assert ch.subscriber_count == 412_000


def test_yt_client_fetch_channels_parses_snapshot(client):
    got = client.fetch_channels(["UCtest000000000000000002"])
    s = got[0].snapshot
    assert s.channel_id == "UCtest000000000000000002"
    assert s.subscriber_count == 23_400
    assert s.view_count == 1_980_000
    assert s.video_count == 88


# ---------------------------------------------------------------- 배치·쿼터


def test_yt_client_batches_ids_by_fifty(client):
    """50개 배치가 쿼터 전략의 핵심 — 1 유닛으로 50개를 조회한다 (PLAN §1)."""
    ids = [f"pad{i:08d}" for i in range(120)]
    client.fetch_videos(ids)
    assert client.quota.calls["videos.list"] == 3, "120개 → 3회 호출"
    assert client.quota.spent == 3


def test_yt_client_single_batch_costs_one_unit(client):
    client.fetch_videos(["vidHarness1", "vidHarness2", "vidHarness3"])
    assert client.quota.spent == 1


def test_yt_client_respects_quota_limit():
    settings = Settings.from_env()
    client = get_youtube_client(settings, quota=QuotaLedger(limit=1))
    client.fetch_videos(["vidHarness1"])
    with pytest.raises(QuotaExceeded):
        client.fetch_channels(["UCtest000000000000000001"])


# ---------------------------------------------------------------- search (발굴)


def test_yt_client_search_channels_returns_channel_refs(client):
    refs = client.search_channels("먹방")
    assert [r.channel_id for r in refs] == [
        "UCtest000000000000000001",
        "UCtest000000000000000002",
    ]
    assert refs[0].title == "하네스푸드"


def test_yt_client_search_channels_filters_non_channel_results(client):
    """type=channel 이라도 방어적으로 걸러야 한다 — 영상 결과가 섞이면 안 된다."""
    refs = client.search_channels("먹방")
    assert all(r.channel_id.startswith("UC") for r in refs)
    assert len(refs) == 2, "영상 결과 1건은 제외돼야 한다"


def test_yt_client_search_costs_one_hundred_units(client):
    """search.list 는 100 units — 이 비용이 예산제 설계의 이유다."""
    client.search_channels("먹방")
    assert client.quota.spent == 100
    assert client.quota.calls["search.list"] == 1


def test_yt_client_search_respects_call_budget():
    settings = Settings.from_env()
    client = get_youtube_client(
        settings, quota=QuotaLedger(limit=100_000, search_budget_calls=2)
    )
    client.search_channels("먹방")
    client.search_channels("맛집")
    with pytest.raises(QuotaExceeded, match="search"):
        client.search_channels("요리")


def test_yt_client_search_via_videos_dedupes_channels(client):
    """같은 채널의 영상이 여러 건 잡혀도 채널은 1회만 집계돼야 한다."""
    refs = client.search_channels_via_videos("자취 요리")
    assert [r.channel_id for r in refs] == [
        "UCtest000000000000000002",
        "UCtest000000000000000001",
    ]


def test_yt_client_search_via_videos_filters_channel_results(client):
    """영상 검색 결과에 채널 항목이 섞이면 제외해야 한다."""
    refs = client.search_channels_via_videos("자취 요리")
    assert "UCtest000000000000000009" not in [r.channel_id for r in refs]


def test_yt_client_search_via_videos_costs_one_hundred_units(client):
    client.search_channels_via_videos("자취 요리")
    assert client.quota.spent == 100
    assert client.quota.calls["search.list"] == 1


def test_yt_client_search_blocked_by_budget_leaves_quota_intact():
    settings = Settings.from_env()
    client = get_youtube_client(settings, quota=QuotaLedger(limit=150))
    client.search_channels("먹방")
    with pytest.raises(QuotaExceeded):
        client.search_channels("맛집")  # 200 > 150
    assert client.quota.spent == 100, "차단된 호출은 소모하지 않는다"
