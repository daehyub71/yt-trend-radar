# -*- coding: utf-8 -*-
"""정규화 velocity 지수와 4종 랭킹 (SPEC FR-2~FR-5, FR-7).

## 왜 이 산식인가

유튜브는 2025-07 에 Trending 을 폐지했고 API 도 Music/Movies/Gaming 차트만 준다.
카테고리별 "지금 뜨는"은 **우리가 직접 계산**해야 한다 — 이 모듈이 그 계산이다.

    score = Δ값 / (Δ시간h × max(구독자, floor) ** α)

α 하나로 두 성격의 보드를 만든다 (SPEC D2 확정):
  - **지금 뜨는** α 낮음 → 분모가 거의 상수. 절대 증가량이 큰 쪽이 위 = 실제로 화제인 것
  - **신규 뜨는** α 높음 → 구독자로 나눈다. 구독자 대비 성과가 좋은 소형 채널이 위 = 발굴

## 설계상 중요한 두 가지

1. **Δ시간은 실측한다.** GitHub Actions cron 은 밀린다(무료 티어). 8시간 간격을 가정하면
   지연된 주기에서 속도가 부풀거나 꺼진다. 스냅샷 시각 차이를 그대로 쓴다.
2. **결측·역행에 견딘다.** 통계 비공개 구간(None)은 건너뛰고, 조회수가 줄어드는 경우
   (유튜브의 가짜 조회수 회수)는 0으로 클램프한다. 콜드스타트에는 스냅샷이 1개뿐인
   대상이 많은데, 그런 대상은 보드에서 조용히 빠진다.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.config import TrendParams
from core.models import Channel, ChannelSnapshot, TrendScore, Video, VideoSnapshot

DEFAULT_LIMIT = 50


@dataclass(frozen=True)
class ScoreConfig:
    """보드 하나의 산출 규격. frozen — 실수로 바꾸면 보드 전체가 흔들린다."""

    alpha: float          # 구독자 정규화 지수 (0=정규화 없음)
    floor: int            # 구독자 하한. 초소형 채널이 분모를 붕괴시키는 것을 막는다
    window_hours: float   # 속도를 재는 구간
    field: str            # 증가량을 잴 필드: 'view_count' | 'subscriber_count'
    kind: str = "trending"                # 'trending' | 'rising'
    max_age_hours: float | None = None    # 영상 나이 상한 (오래된 영상 배제)
    max_subscribers: int | None = None    # 구독자 상한 (rising 채널용)

    def __post_init__(self):
        if self.alpha < 0:
            raise ValueError("alpha 는 음수일 수 없습니다")
        if self.floor < 1:
            raise ValueError("floor 는 1 이상이어야 합니다")
        if self.window_hours <= 0:
            raise ValueError("window_hours 는 양수여야 합니다")
        if self.kind not in ("trending", "rising"):
            raise ValueError(f"kind 는 trending|rising 이어야 합니다: {self.kind}")
        # rising 보드의 α<1 은 조용한 성능 저하가 아니라 **기능 상실**이다 — 크게 실패시킨다
        if self.kind == "rising" and self.alpha < 1.0:
            raise ValueError(
                f"rising 보드의 alpha 는 1.0 이상이어야 합니다 (받은 값 {self.alpha}). "
                "1 미만이면 구독자 규모 순으로 되돌아갑니다."
            )


# --- 보드별 기본 설정 -------------------------------------------------------
#
# ## α = 1.0 이어야 하는 이유 (2026-08-03 시연에서 교정)
#
# 처음에 rising 을 α=0.7 로 뒀다가, 모든 채널이 "구독자의 8%"에 해당하는 조회수를 얻는
# 시나리오를 돌려보니 **신규 뜨는 보드가 구독자 내림차순 그대로**였다. 산식을 풀면 당연하다:
#
#     Δ ∝ 구독자  일 때   score = Δ / (h × 구독자^α) ∝ 구독자^(1-α)
#
# α<1 이면 지수가 양수라 규모가 계속 이긴다. **α=1.0 에서만** score 가 규모와 무관한
# "구독자 1명당 조회수 증가"가 된다 — 이것이 '구독자 대비 성과'의 정의다.
# 실제로 소형 채널의 터진 영상은 구독자의 10~100배 조회수를 얻고, 대형 채널은 0.5배를
# 넘기 어렵다. 그래서 α=1.0 이면 자연히 소형 채널이 위로 온다.
#
# TRENDING 은 반대로 절대 규모를 살리되(α 작게), 0 은 아니다 — 대형 채널의 평범한 실적이
# 보드를 점령하지 않도록 완만한 핸디캡을 준다. 유튜브 공식 Trending 이 지루했던 이유다.
#
# α 값은 콜드스타트 실데이터로 재조정한다. 단 RISING.alpha > TRENDING.alpha 와
# RISING.alpha >= 1.0 은 규약이며 테스트가 지킨다.

# 구간 길이는 데이터 특성(수집 주기·영상 수명)에서 오므로 코드가 소유한다.
# α·floor·구독자 상한은 튜닝 대상이라 `TrendParams`(=.env) 가 소유한다.
VIDEO_WINDOW_HOURS = 48
VIDEO_MAX_AGE_HOURS = 24 * 7
CHANNEL_WINDOW_HOURS = 24 * 7

# 영상 보드는 형식별로 나눈다. 채널 보드에는 이 축이 없다.
VIDEO_FORMATS = ("long", "short")


def configs_from(params: TrendParams) -> list[tuple[str, str, ScoreConfig]]:
    """설정에서 4개 보드 규격을 만든다.

    **여기가 단일 진실이다.** 예전에는 엔진이 α 를 하드코딩하고 `.env` 에도 따로 값이 있어,
    `.env` 쪽이 죽은 설정이 된 채 규약(α≥1.0)을 위반하는 값을 담고 있었다(2026-08-03 발견).
    """
    return [
        ("video", "trending", ScoreConfig(
            alpha=params.alpha_trending, floor=params.subscriber_floor,
            window_hours=VIDEO_WINDOW_HOURS, field="view_count", kind="trending",
            max_age_hours=VIDEO_MAX_AGE_HOURS)),
        ("video", "rising", ScoreConfig(
            alpha=params.alpha_rising, floor=params.subscriber_floor,
            window_hours=VIDEO_WINDOW_HOURS, field="view_count", kind="rising",
            max_age_hours=VIDEO_MAX_AGE_HOURS)),
        ("channel", "trending", ScoreConfig(
            alpha=params.alpha_trending, floor=params.subscriber_floor,
            window_hours=CHANNEL_WINDOW_HOURS, field="view_count", kind="trending")),
        ("channel", "rising", ScoreConfig(
            alpha=params.alpha_rising, floor=params.subscriber_floor,
            window_hours=CHANNEL_WINDOW_HOURS, field="subscriber_count", kind="rising",
            max_subscribers=params.rising_subscriber_max)),  # SPEC D7
    ]


DEFAULT_BOARDS = configs_from(TrendParams())
BOARDS = DEFAULT_BOARDS  # 하위 호환 별칭

TRENDING_VIDEO = DEFAULT_BOARDS[0][2]
RISING_VIDEO = DEFAULT_BOARDS[1][2]
TRENDING_CHANNEL = DEFAULT_BOARDS[2][2]
RISING_CHANNEL = DEFAULT_BOARDS[3][2]


# --- 핵심 계산 --------------------------------------------------------------


def window_delta(
    snapshots: list, now: datetime, window_hours: float, field: str
) -> tuple[int, float] | None:
    """구간 내 첫↔마지막 스냅샷의 (증가량, 실측 시간h). 계산 불가면 None.

    None 인 경우: 값 있는 스냅샷이 2개 미만이거나, 두 시각이 같을 때.
    """
    cutoff = now - timedelta(hours=window_hours)
    usable = [
        s for s in snapshots if getattr(s, field, None) is not None and s.ts >= cutoff
    ]
    if len(usable) < 2:
        return None

    usable.sort(key=lambda s: s.ts)
    first, last = usable[0], usable[-1]
    hours = (last.ts - first.ts).total_seconds() / 3600
    if hours <= 0:
        return None

    delta = getattr(last, field) - getattr(first, field)
    return max(0, delta), hours  # 역행은 0으로 클램프


def normalized_velocity(
    delta: int, hours: float, subscriber_count: int | None, alpha: float, floor: int
) -> float:
    """정규화 속도. hours 가 0 이하이면 0 (호출자가 이미 걸러내지만 방어한다)."""
    if hours <= 0:
        return 0.0
    denom = max(subscriber_count or 0, floor) ** alpha
    return delta / hours / denom


# --- 랭킹 -------------------------------------------------------------------


def _finalize(scored: list[tuple[float, TrendScore]], limit: int) -> list[TrendScore]:
    """점수 내림차순 → 순위 부여. 동점은 target_id 오름차순으로 결정적으로 깬다."""
    scored.sort(key=lambda p: (-p[0], p[1].target_id))
    out = []
    for i, (_, s) in enumerate(scored[:limit], start=1):
        s.rank = i
        out.append(s)
    return out


def rank_videos(
    videos: list[Video],
    snapshots_by_video: dict[str, list[VideoSnapshot]],
    channels_by_id: dict[str, Channel],
    config: ScoreConfig,
    now: datetime,
    category_id: str,
    region: str | None = None,
    limit: int = DEFAULT_LIMIT,
    video_format: str | None = None,
) -> list[TrendScore]:
    """video_format: 'long' | 'short' | None(혼재).

    실측(2026-08-03): 추적 영상의 63%가 Shorts 였고 보드의 67%를 차지했다.
    Shorts 는 조회수 획득 속도 자체가 달라, 섞으면 롱폼이 노출되지 않는다.
    """
    kind = config.kind
    scored: list[tuple[float, TrendScore]] = []

    for v in videos:
        if v.category_id != category_id:
            continue
        if region is not None and v.region != region:
            continue
        if video_format is not None and v.is_short != (video_format == "short"):
            continue
        if config.max_age_hours is not None:
            age_h = (now - v.published_at).total_seconds() / 3600
            if age_h > config.max_age_hours:
                continue

        measured = window_delta(
            snapshots_by_video.get(v.id, []), now, config.window_hours, config.field
        )
        if measured is None:
            continue
        delta, hours = measured
        if delta <= 0:
            continue  # 증가 없는 영상으로 보드를 채우지 않는다

        ch = channels_by_id.get(v.channel_id)
        subs = ch.subscriber_count if ch else None
        score = normalized_velocity(delta, hours, subs, config.alpha, config.floor)
        if score <= 0:
            continue

        scored.append(
            (
                score,
                TrendScore(
                    scope="video", kind=kind, category_id=category_id, region=region,
                    format=video_format, rank=0, score=score, target_id=v.id,
                    title=v.title,
                    channel_id=v.channel_id,
                    channel_title=ch.title if ch else None,
                    thumbnail_url=v.thumbnail_url,
                    published_at=v.published_at,
                    view_count=v.view_count,
                    subscriber_count=subs,
                    delta_views=delta,
                    window_hours=round(hours, 2),
                ),
            )
        )
    return _finalize(scored, limit)


def rank_channels(
    channels: list[Channel],
    snapshots_by_channel: dict[str, list[ChannelSnapshot]],
    config: ScoreConfig,
    now: datetime,
    category_id: str,
    region: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[TrendScore]:
    kind = config.kind
    scored: list[tuple[float, TrendScore]] = []

    for ch in channels:
        if ch.category_id != category_id:
            continue
        if region is not None and ch.region != region:
            continue
        if config.max_subscribers is not None and (ch.subscriber_count or 0) > config.max_subscribers:
            continue

        measured = window_delta(
            snapshots_by_channel.get(ch.id, []), now, config.window_hours, config.field
        )
        if measured is None:
            continue
        delta, hours = measured
        if delta <= 0:
            continue

        score = normalized_velocity(
            delta, hours, ch.subscriber_count, config.alpha, config.floor
        )
        if score <= 0:
            continue

        # 채널 보드에서도 delta_views 컬럼을 쓴다 — rising 은 구독자 증가분이 담긴다
        scored.append(
            (
                score,
                TrendScore(
                    scope="channel", kind=kind, category_id=category_id, region=region,
                    rank=0, score=score, target_id=ch.id,
                    title=ch.title,
                    channel_id=ch.id,
                    channel_title=ch.title,
                    thumbnail_url=ch.thumbnail_url,
                    subscriber_count=ch.subscriber_count,
                    delta_views=delta,
                    window_hours=round(hours, 2),
                ),
            )
        )
    return _finalize(scored, limit)


def build_boards(
    categories: list[str],
    videos: list[Video],
    video_snapshots: dict[str, list[VideoSnapshot]],
    channels: list[Channel],
    channel_snapshots: dict[str, list[ChannelSnapshot]],
    now: datetime,
    regions: list[str | None] | None = None,
    limit: int = DEFAULT_LIMIT,
    params: TrendParams | None = None,
) -> list[TrendScore]:
    """모든 카테고리 × 4종 보드를 만든다. 순위는 보드마다 1부터 다시 매긴다.

    params 를 주면 그 설정으로 보드 규격을 만든다 (없으면 기본값).
    """
    boards = configs_from(params) if params else DEFAULT_BOARDS
    channels_by_id = {c.id: c for c in channels}
    out: list[TrendScore] = []

    for category_id in categories:
        for region in regions or [None]:
            for scope, _kind, config in boards:
                if scope == "video":
                    # 롱폼/Shorts 를 별도 보드로 산출한다 (섞으면 롱폼이 묻힌다)
                    for fmt in VIDEO_FORMATS:
                        out.extend(
                            rank_videos(videos, video_snapshots, channels_by_id, config,
                                        now, category_id, region, limit, video_format=fmt)
                        )
                else:
                    out.extend(
                        rank_channels(channels, channel_snapshots, config,
                                      now, category_id, region, limit)
                    )
    return out
