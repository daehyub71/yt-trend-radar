# -*- coding: utf-8 -*-
"""engine.trend_engine — 정규화 velocity 지수와 4종 랭킹 (SPEC FR-2~FR-5, FR-7).

산식 (SPEC D2 확정):
    score = Δ값 / (Δ시간h × max(구독자, floor) ** α)

α 가 이 서비스의 핵심 손잡이다:
  - "지금 뜨는"  → α 낮음: 절대 규모가 반영돼 큰 채널의 히트가 위로
  - "신규 뜨는"  → α 높음: 구독자 대비 성과가 반영돼 소형 채널의 히트가 위로

Δ시간은 **실측**한다. 수집 주기가 흔들려도(Actions 지연) 결과가 맞아야 하기 때문이다.
"""
from datetime import datetime, timedelta, timezone

import pytest

from core.models import Channel, ChannelSnapshot, Video, VideoSnapshot
from engine.trend_engine import (
    RISING_CHANNEL,
    RISING_VIDEO,
    TRENDING_CHANNEL,
    TRENDING_VIDEO,
    ScoreConfig,
    build_boards,
    normalized_velocity,
    rank_channels,
    rank_videos,
    window_delta,
)

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def ts(hours_ago: float) -> datetime:
    return NOW - timedelta(hours=hours_ago)


def vsnap(vid: str, hours_ago: float, views: int | None) -> VideoSnapshot:
    return VideoSnapshot(video_id=vid, ts=ts(hours_ago), view_count=views)


def csnap(cid: str, hours_ago: float, subs: int | None = None, views: int | None = None):
    return ChannelSnapshot(channel_id=cid, ts=ts(hours_ago), subscriber_count=subs, view_count=views)


# ================================================================= window_delta


def test_trend_window_delta_uses_measured_interval():
    """Δ시간은 가정(8시간)이 아니라 스냅샷 시각 차이로 잰다."""
    snaps = [vsnap("v", 10, 1_000), vsnap("v", 2, 5_000)]
    delta, hours = window_delta(snaps, NOW, window_hours=48, field="view_count")
    assert delta == 4_000
    assert hours == pytest.approx(8.0)


def test_trend_window_delta_handles_irregular_intervals():
    """수집이 밀려 간격이 들쭉날쭉해도 첫↔마지막 실측 간격을 쓴다."""
    snaps = [vsnap("v", 30, 100), vsnap("v", 25, 300), vsnap("v", 1, 900)]
    delta, hours = window_delta(snaps, NOW, window_hours=48, field="view_count")
    assert delta == 800
    assert hours == pytest.approx(29.0)


def test_trend_window_delta_needs_two_snapshots():
    assert window_delta([vsnap("v", 3, 100)], NOW, 48, "view_count") is None
    assert window_delta([], NOW, 48, "view_count") is None


def test_trend_window_delta_ignores_snapshots_outside_window():
    """구간 밖 스냅샷은 무시한다 — '지금 뜨는'은 최근 구간의 속도다."""
    snaps = [vsnap("v", 200, 10), vsnap("v", 6, 1_000), vsnap("v", 1, 1_500)]
    delta, hours = window_delta(snaps, NOW, window_hours=48, field="view_count")
    assert delta == 500
    assert hours == pytest.approx(5.0)


def test_trend_window_delta_returns_none_when_window_has_one_point():
    snaps = [vsnap("v", 200, 10), vsnap("v", 1, 1_500)]
    assert window_delta(snaps, NOW, window_hours=48, field="view_count") is None


def test_trend_window_delta_zero_duration_returns_none():
    """같은 시각 스냅샷 두 개 — 0으로 나누면 안 된다."""
    snaps = [vsnap("v", 5, 100), vsnap("v", 5, 200)]
    assert window_delta(snaps, NOW, 48, "view_count") is None


def test_trend_window_delta_clamps_negative_delta():
    """유튜브는 가짜 조회수를 회수하기도 한다 — 음수 증가량은 0으로 본다."""
    snaps = [vsnap("v", 10, 5_000), vsnap("v", 2, 4_000)]
    delta, _ = window_delta(snaps, NOW, 48, "view_count")
    assert delta == 0


def test_trend_window_delta_skips_none_values():
    """통계 비공개 구간이 섞여도 값이 있는 스냅샷만으로 계산한다."""
    snaps = [vsnap("v", 10, None), vsnap("v", 8, 1_000), vsnap("v", 2, 3_000)]
    delta, hours = window_delta(snaps, NOW, 48, "view_count")
    assert delta == 2_000
    assert hours == pytest.approx(6.0)


def test_trend_window_delta_reads_requested_field():
    snaps = [csnap("c", 12, subs=1_000, views=10), csnap("c", 2, subs=1_500, views=99)]
    assert window_delta(snaps, NOW, 48, "subscriber_count")[0] == 500
    assert window_delta(snaps, NOW, 48, "view_count")[0] == 89


# ============================================================ normalized_velocity


def test_trend_velocity_is_views_per_hour_when_alpha_zero():
    """α=0 이면 순수 시간당 증가량 — 정규화 없음."""
    assert normalized_velocity(4_000, 8.0, 1_000_000, alpha=0.0, floor=1_000) == pytest.approx(500.0)


def test_trend_velocity_alpha_penalizes_large_channels():
    """같은 증가량이면 큰 채널일수록 점수가 낮아야 한다 (rising 의 핵심)."""
    small = normalized_velocity(1_000, 1.0, 10_000, alpha=0.5, floor=1_000)
    big = normalized_velocity(1_000, 1.0, 1_000_000, alpha=0.5, floor=1_000)
    assert small > big
    assert big == pytest.approx(1_000 / (1_000_000**0.5))


def test_trend_velocity_uses_floor_for_tiny_channels():
    """구독자 0~수십인 채널이 분모를 붕괴시켜 점수를 폭주시키면 안 된다."""
    tiny = normalized_velocity(1_000, 1.0, 5, alpha=0.5, floor=1_000)
    at_floor = normalized_velocity(1_000, 1.0, 1_000, alpha=0.5, floor=1_000)
    assert tiny == at_floor


def test_trend_velocity_missing_subscribers_uses_floor():
    assert normalized_velocity(500, 1.0, None, alpha=0.5, floor=1_000) == pytest.approx(
        normalized_velocity(500, 1.0, 1_000, alpha=0.5, floor=1_000)
    )


def test_trend_velocity_zero_hours_is_zero_not_crash():
    assert normalized_velocity(500, 0.0, 1_000, alpha=0.5, floor=1_000) == 0.0


# ================================================================= 설정 규약


def test_trend_configs_rising_alpha_exceeds_trending():
    """SPEC FR-7: 같은 산식의 α 차이로 두 보드를 만든다 — 이 관계가 깨지면 보드가 같아진다."""
    assert RISING_VIDEO.alpha > TRENDING_VIDEO.alpha
    assert RISING_CHANNEL.alpha > TRENDING_CHANNEL.alpha


def test_trend_rising_alpha_is_at_least_one():
    """α<1 이면 '신규 뜨는'이 여전히 규모 순이 된다 — 실측으로 확인된 실패 모드.

    Δ ∝ 구독자일 때 score ∝ 구독자^(1-α) 이므로, α=1 에서만 규모 중립이 된다.
    """
    assert RISING_VIDEO.alpha >= 1.0
    assert RISING_CHANNEL.alpha >= 1.0


def test_trend_rising_is_size_neutral_at_equal_relative_performance():
    """모든 채널이 '구독자의 8%'만큼 조회수를 얻으면 rising 점수는 규모와 무관해야 한다.

    2026-08-03 시연에서 α=0.7 이 이 성질을 깨고 보드를 구독자 내림차순으로 만들었다.
    """
    scores = []
    for subs in (5_000, 100_000, 2_000_000, 16_800_000):
        gained = int(subs * 0.08)
        scores.append(
            normalized_velocity(gained, 8.0, subs, RISING_VIDEO.alpha, RISING_VIDEO.floor)
        )
    assert max(scores) == pytest.approx(min(scores), rel=1e-9)


def test_trend_rising_favors_outperforming_small_channel():
    """소형 채널이 구독자의 10배 조회수 → 대형 채널의 0.1배보다 훨씬 위."""
    small = normalized_velocity(50_000, 8.0, 5_000, RISING_VIDEO.alpha, RISING_VIDEO.floor)
    big = normalized_velocity(1_680_000, 8.0, 16_800_000, RISING_VIDEO.alpha, RISING_VIDEO.floor)
    assert small > big * 50


def test_trend_trending_still_rewards_absolute_scale():
    """반대로 trending 은 규모가 반영돼야 한다 (α<1)."""
    assert TRENDING_VIDEO.alpha < 1.0
    small = normalized_velocity(50_000, 8.0, 5_000, TRENDING_VIDEO.alpha, TRENDING_VIDEO.floor)
    big = normalized_velocity(1_680_000, 8.0, 16_800_000, TRENDING_VIDEO.alpha, TRENDING_VIDEO.floor)
    assert big > small


def test_trend_rising_channel_caps_subscribers_at_spec_threshold():
    """SPEC D7: 신규 뜨는 유튜버는 구독자 10만 이하."""
    assert RISING_CHANNEL.max_subscribers == 100_000
    assert TRENDING_CHANNEL.max_subscribers is None


def test_trend_channel_configs_use_expected_metric():
    """FR-4 는 조회수 성장, FR-5 는 구독자 성장을 본다."""
    assert TRENDING_CHANNEL.field == "view_count"
    assert RISING_CHANNEL.field == "subscriber_count"


# ================================================================= 영상 랭킹


@pytest.fixture
def video_fixture():
    channels = {
        "UCbig": Channel(id="UCbig", title="대형채널", subscriber_count=1_000_000,
                         category_id="food"),
        "UCsmall": Channel(id="UCsmall", title="소형채널", subscriber_count=5_000,
                           category_id="food"),
    }
    videos = [
        Video(id="vBig0000000", channel_id="UCbig", title="대형 채널 영상",
              published_at=ts(24), category_id="food", view_count=450_000),
        Video(id="vSmall00000", channel_id="UCsmall", title="소형 채널 영상",
              published_at=ts(24), category_id="food", view_count=52_000),
    ]
    snaps = {
        # 대형 채널이 절대 증가량 10배 (400,000 vs 40,000),
        # 소형 채널은 구독자 대비 성과 8배 (40,000 / 5,000구독 vs 400,000 / 100만구독)
        "vBig0000000": [vsnap("vBig0000000", 10, 50_000), vsnap("vBig0000000", 2, 450_000)],
        "vSmall00000": [vsnap("vSmall00000", 10, 12_000), vsnap("vSmall00000", 2, 52_000)],
    }
    return videos, snaps, channels


def test_rank_trending_favors_absolute_scale(video_fixture):
    """지금 뜨는: 절대 증가량이 큰 대형 채널 영상이 위."""
    videos, snaps, channels = video_fixture
    board = rank_videos(videos, snaps, channels, TRENDING_VIDEO, NOW, "food")
    assert [s.target_id for s in board] == ["vBig0000000", "vSmall00000"]


def test_rank_rising_favors_small_channel(video_fixture):
    """신규 뜨는: 구독자 대비 성과가 좋은 소형 채널 영상이 위 — 보드가 실제로 달라야 한다."""
    videos, snaps, channels = video_fixture
    board = rank_videos(videos, snaps, channels, RISING_VIDEO, NOW, "food")
    assert [s.target_id for s in board] == ["vSmall00000", "vBig0000000"]


def test_rank_videos_assigns_sequential_ranks(video_fixture):
    videos, snaps, channels = video_fixture
    board = rank_videos(videos, snaps, channels, TRENDING_VIDEO, NOW, "food")
    assert [s.rank for s in board] == [1, 2]
    assert all(s.scope == "video" for s in board)
    assert {s.kind for s in board} == {"trending"}


def test_rank_videos_populates_display_fields(video_fixture):
    """웹이 조인 없이 카드를 그린다 (PLAN §3) — 표시 필드가 채워져야 한다."""
    videos, snaps, channels = video_fixture
    top = rank_videos(videos, snaps, channels, TRENDING_VIDEO, NOW, "food")[0]
    assert top.title == "대형 채널 영상"
    assert top.channel_title == "대형채널"
    assert top.subscriber_count == 1_000_000
    assert top.delta_views == 400_000
    assert top.window_hours == pytest.approx(8.0)
    assert top.category_id == "food"


def test_rank_trending_still_handicaps_large_channels():
    """'지금 뜨는'도 순수 조회수가 아니다 (α=0 이 아님).

    증가량이 비슷하면(1.25배) 구독자 200배 차이를 이기지 못한다 —
    대형 채널의 평범한 실적이 보드를 점령하지 않게 하는 의도적 설계다.
    유튜브 공식 Trending 이 지루했던 이유가 이 손잡이의 부재였다.
    """
    channels = {
        "UCbig": Channel(id="UCbig", title="대형", subscriber_count=1_000_000, category_id="food"),
        "UCsmall": Channel(id="UCsmall", title="소형", subscriber_count=5_000, category_id="food"),
    }
    videos = [
        Video(id="vBig0000000", channel_id="UCbig", title="B", published_at=ts(24),
              category_id="food"),
        Video(id="vSmall00000", channel_id="UCsmall", title="S", published_at=ts(24),
              category_id="food"),
    ]
    snaps = {
        "vBig0000000": [vsnap("vBig0000000", 10, 50_000), vsnap("vBig0000000", 2, 100_000)],
        "vSmall00000": [vsnap("vSmall00000", 10, 12_000), vsnap("vSmall00000", 2, 52_000)],
    }
    board = rank_videos(videos, snaps, channels, TRENDING_VIDEO, NOW, "food")
    assert board[0].target_id == "vSmall00000"


def test_rank_videos_excludes_videos_older_than_max_age(video_fixture):
    """지금 뜨는 영상은 최근 업로드만 — 오래된 영상이 누적 조회수로 눌러앉으면 안 된다."""
    videos, snaps, channels = video_fixture
    videos[0].published_at = ts(24 * 30)  # 30일 전
    board = rank_videos(videos, snaps, channels, TRENDING_VIDEO, NOW, "food")
    assert [s.target_id for s in board] == ["vSmall00000"]


def test_rank_videos_excludes_insufficient_snapshots(video_fixture):
    """스냅샷이 1개뿐이면 속도를 알 수 없다 — 콜드스타트 구간에서 실제로 발생한다."""
    videos, snaps, channels = video_fixture
    snaps["vBig0000000"] = [vsnap("vBig0000000", 2, 100_000)]
    board = rank_videos(videos, snaps, channels, TRENDING_VIDEO, NOW, "food")
    assert [s.target_id for s in board] == ["vSmall00000"]


def test_rank_videos_filters_by_category(video_fixture):
    videos, snaps, channels = video_fixture
    videos[0].category_id = "travel"
    board = rank_videos(videos, snaps, channels, TRENDING_VIDEO, NOW, "food")
    assert [s.target_id for s in board] == ["vSmall00000"]


def test_rank_videos_respects_limit(video_fixture):
    videos, snaps, channels = video_fixture
    assert len(rank_videos(videos, snaps, channels, TRENDING_VIDEO, NOW, "food", limit=1)) == 1


def test_rank_videos_drops_zero_score(video_fixture):
    """증가량 0인 영상은 보드에 올리지 않는다 (죽은 영상으로 자리를 채우지 않는다)."""
    videos, snaps, channels = video_fixture
    snaps["vBig0000000"] = [vsnap("vBig0000000", 10, 100_000), vsnap("vBig0000000", 2, 100_000)]
    board = rank_videos(videos, snaps, channels, TRENDING_VIDEO, NOW, "food")
    assert [s.target_id for s in board] == ["vSmall00000"]


def test_rank_videos_tiebreak_is_deterministic():
    """동점이면 항상 같은 순서 — 매 주기 순위가 흔들리면 신뢰를 잃는다."""
    channels = {"UCa": Channel(id="UCa", title="채널", subscriber_count=10_000)}
    videos = [
        Video(id="vZZZ0000000", channel_id="UCa", title="Z", published_at=ts(5), category_id="food"),
        Video(id="vAAA0000000", channel_id="UCa", title="A", published_at=ts(5), category_id="food"),
    ]
    snaps = {
        v.id: [vsnap(v.id, 8, 1_000), vsnap(v.id, 2, 3_000)] for v in videos
    }
    first = [s.target_id for s in rank_videos(videos, snaps, channels, TRENDING_VIDEO, NOW, "food")]
    second = [s.target_id for s in rank_videos(videos, snaps, channels, TRENDING_VIDEO, NOW, "food")]
    assert first == second == ["vAAA0000000", "vZZZ0000000"]


# ================================================================= 채널 랭킹


@pytest.fixture
def channel_fixture():
    channels = [
        Channel(id="UCbig", title="대형", subscriber_count=800_000, category_id="food"),
        Channel(id="UCmid", title="중형", subscriber_count=90_000, category_id="food"),
        Channel(id="UCtiny", title="소형", subscriber_count=4_000, category_id="food"),
    ]
    snaps = {
        "UCbig": [csnap("UCbig", 24, subs=795_000, views=50_000_000),
                  csnap("UCbig", 0, subs=800_000, views=50_900_000)],
        "UCmid": [csnap("UCmid", 24, subs=87_000, views=8_000_000),
                  csnap("UCmid", 0, subs=90_000, views=8_200_000)],
        "UCtiny": [csnap("UCtiny", 24, subs=3_000, views=200_000),
                   csnap("UCtiny", 0, subs=4_000, views=260_000)],
    }
    return channels, snaps


def test_rank_channels_trending_uses_view_growth(channel_fixture):
    channels, snaps = channel_fixture
    board = rank_channels(channels, snaps, TRENDING_CHANNEL, NOW, "food")
    assert board[0].target_id == "UCbig"
    assert board[0].scope == "channel"
    assert board[0].delta_views == 900_000


def test_rank_channels_rising_excludes_large_channels(channel_fixture):
    """SPEC D7: 구독자 10만 초과는 '신규 뜨는 유튜버'가 아니다."""
    channels, snaps = channel_fixture
    board = rank_channels(channels, snaps, RISING_CHANNEL, NOW, "food")
    assert "UCbig" not in [s.target_id for s in board]
    assert {"UCmid", "UCtiny"} == {s.target_id for s in board}


def test_rank_channels_rising_favors_relative_growth(channel_fixture):
    """소형(3천→4천, +33%)이 중형(8.7만→9만, +3%)보다 위."""
    channels, snaps = channel_fixture
    board = rank_channels(channels, snaps, RISING_CHANNEL, NOW, "food")
    assert board[0].target_id == "UCtiny"


def test_rank_channels_populates_display_fields(channel_fixture):
    channels, snaps = channel_fixture
    top = rank_channels(channels, snaps, TRENDING_CHANNEL, NOW, "food")[0]
    assert top.title == "대형"
    assert top.channel_id == "UCbig"
    assert top.subscriber_count == 800_000


# ================================================================= 보드 생성


def test_build_boards_creates_four_boards_per_category(video_fixture, channel_fixture):
    videos, vsnaps, _ = video_fixture
    channels, csnaps = channel_fixture
    boards = build_boards(
        categories=["food"], videos=videos, video_snapshots=vsnaps,
        channels=channels, channel_snapshots=csnaps, now=NOW,
    )
    got = {(s.scope, s.kind) for s in boards}
    assert got == {("video", "trending"), ("video", "rising"),
                   ("channel", "trending"), ("channel", "rising")}


def test_build_boards_ranks_restart_per_board(video_fixture, channel_fixture):
    videos, vsnaps, _ = video_fixture
    channels, csnaps = channel_fixture
    boards = build_boards(
        categories=["food"], videos=videos, video_snapshots=vsnaps,
        channels=channels, channel_snapshots=csnaps, now=NOW,
    )
    for key in {(s.scope, s.kind, s.category_id) for s in boards}:
        ranks = [s.rank for s in boards
                 if (s.scope, s.kind, s.category_id) == key]
        assert ranks == list(range(1, len(ranks) + 1))


def test_build_boards_empty_input_is_safe():
    assert build_boards(categories=["food"], videos=[], video_snapshots={},
                        channels=[], channel_snapshots={}, now=NOW) == []


def test_score_config_is_immutable():
    """설정을 실수로 바꾸면 보드 전체가 흔들린다."""
    with pytest.raises(Exception):
        TRENDING_VIDEO.alpha = 9.9  # type: ignore[misc]


def test_score_config_rejects_negative_alpha():
    with pytest.raises(ValueError):
        ScoreConfig(alpha=-1, floor=1000, window_hours=48, field="view_count")


# ------------------------------------------------- 설정 단일화 회귀 (2026-08-03)
# 사고: 엔진이 α 를 하드코딩하고 .env 에도 별도 값(0.35/0.75)이 있었다. .env 쪽은 아무 데도
# 연결되지 않은 죽은 설정이었고, 값 자체가 α≥1.0 규약을 위반했다. 연결하는 순간
# '신규 뜨는' 보드가 조용히 구독자 순으로 되돌아갈 상태였다.


def test_score_config_rejects_rising_alpha_below_one():
    """rising 보드의 α<1 은 조용한 저하가 아니라 기능 상실 — 생성 자체를 막는다."""
    with pytest.raises(ValueError, match="1.0 이상"):
        ScoreConfig(alpha=0.75, floor=1000, window_hours=48, field="view_count", kind="rising")


def test_score_config_rejects_unknown_kind():
    with pytest.raises(ValueError, match="trending|rising"):
        ScoreConfig(alpha=0.5, floor=1000, window_hours=48, field="view_count", kind="hot")


def test_trend_params_rejects_rising_alpha_below_one():
    from core.config import TrendParams

    with pytest.raises(ValueError, match="1.0 이상"):
        TrendParams(alpha_trending=0.35, alpha_rising=0.75)


def test_trend_params_rejects_rising_not_greater_than_trending():
    from core.config import TrendParams

    with pytest.raises(ValueError):
        TrendParams(alpha_trending=1.5, alpha_rising=1.0)


def test_configs_from_params_drives_the_engine():
    """.env 설정이 실제 보드 규격에 반영돼야 한다 (죽은 설정 금지)."""
    from core.config import TrendParams
    from engine.trend_engine import configs_from

    boards = configs_from(TrendParams(alpha_trending=0.3, alpha_rising=1.2,
                                      subscriber_floor=5_000, rising_subscriber_max=50_000))
    by_key = {(scope, kind): cfg for scope, kind, cfg in boards}
    assert by_key[("video", "trending")].alpha == 0.3
    assert by_key[("video", "rising")].alpha == 1.2
    assert by_key[("video", "rising")].floor == 5_000
    assert by_key[("channel", "rising")].max_subscribers == 50_000


def test_configs_from_defaults_match_module_constants():
    """모듈 상수와 기본 설정이 어긋나면 진실이 다시 둘로 갈라진다."""
    from core.config import TrendParams
    from engine.trend_engine import configs_from

    boards = configs_from(TrendParams())
    assert boards[0][2] == TRENDING_VIDEO
    assert boards[1][2] == RISING_VIDEO
    assert boards[3][2] == RISING_CHANNEL


def test_build_boards_honors_custom_params(video_fixture, channel_fixture):
    """params 를 넘기면 그 설정으로 산출해야 한다."""
    from core.config import TrendParams

    videos, vsnaps, _ = video_fixture
    channels, csnaps = channel_fixture
    boards = build_boards(
        categories=["food"], videos=videos, video_snapshots=vsnaps,
        channels=channels, channel_snapshots=csnaps, now=NOW,
        params=TrendParams(alpha_trending=0.0, alpha_rising=1.0),
    )
    assert boards, "설정을 넘겨도 보드가 나와야 한다"
