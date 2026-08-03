# -*- coding: utf-8 -*-
"""설정과 택소노미 로딩.

- Settings.from_env() 은 .env 를 자동으로 읽지 않는다 (테스트 격리).
  실행 진입점(jobs/, tools/)에서 load_env_file() 을 먼저 호출한다.
- 카테고리/지역 정의의 단일 진실은 config/categories.yaml 이다 (SPEC FR-1).
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_TAXONOMY = PROJECT_ROOT / "config" / "categories.yaml"
DEFAULT_SEEDS = PROJECT_ROOT / "config" / "seeds.yaml"


def load_env_file(path: Path | None = None) -> None:
    """.env 를 환경변수로 주입한다. 이미 설정된 값은 덮어쓰지 않는다."""
    from dotenv import load_dotenv

    load_dotenv(path or (PROJECT_ROOT / ".env"), override=False)


def _f(env, key, default):
    try:
        return float(env.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _i(env, key, default):
    try:
        return int(env.get(key, default))
    except (TypeError, ValueError):
        return int(default)


# ---------------------------------------------------------------- 트렌드 지수


@dataclass(frozen=True)
class TrendParams:
    """score = Δviews / (Δhours * max(subscribers, floor) ** alpha)  — SPEC FR-7.

    ## alpha_rising 은 1.0 이상이어야 한다 (규약)

    Δ가 구독자에 비례할 때 `score ∝ 구독자^(1-alpha)` 이므로, alpha<1 이면 지수가 양수라
    **'신규 뜨는'도 결국 구독자 순**이 된다. 2026-08-03 시연에서 alpha=0.7 로 실제로 그랬다.
    alpha=1.0 에서만 "구독자 1명당 조회수 증가"라는 정의가 성립한다.

    'alpha_rising > alpha_trending' 만으로는 부족하다 — 0.75 > 0.35 도 그 조건은 만족하지만
    보드는 여전히 규모 순이다. 그래서 절대 하한을 함께 강제한다.
    """

    alpha_trending: float = 0.25
    alpha_rising: float = 1.00
    subscriber_floor: int = 1_000
    rising_subscriber_max: int = 100_000

    def __post_init__(self):
        if self.alpha_trending < 0:
            raise ValueError("alpha_trending 은 음수일 수 없습니다")
        if self.alpha_rising < 1.0:
            raise ValueError(
                f"alpha_rising 은 1.0 이상이어야 합니다 (받은 값 {self.alpha_rising}). "
                "1 미만이면 '신규 뜨는' 보드가 구독자 규모 순으로 되돌아갑니다."
            )
        if self.alpha_rising <= self.alpha_trending:
            raise ValueError("alpha_rising 은 alpha_trending 보다 커야 합니다")
        if self.subscriber_floor < 1:
            raise ValueError("subscriber_floor 는 1 이상이어야 합니다")


@dataclass(frozen=True)
class Settings:
    yt_mode: str = "harness"
    db_mode: str = "harness"
    yt_api_key: str = ""
    yt_search_budget_calls: int = 60
    yt_daily_quota_limit: int = 9_500
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_anon_key: str = ""
    retention_days: int = 30
    trend: TrendParams = field(default_factory=TrendParams)

    @property
    def is_harness(self) -> bool:
        return self.yt_mode == "harness" and self.db_mode == "harness"

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Settings":
        e = os.environ if env is None else env
        return cls(
            yt_mode=e.get("YT_MODE", "harness").strip().lower(),
            db_mode=e.get("DB_MODE", "harness").strip().lower(),
            yt_api_key=e.get("YT_API_KEY", "").strip(),
            yt_search_budget_calls=_i(e, "YT_SEARCH_BUDGET_CALLS", 60),
            yt_daily_quota_limit=_i(e, "YT_DAILY_QUOTA_LIMIT", 9_500),
            supabase_url=e.get("SUPABASE_URL", "").strip().rstrip("/"),
            supabase_service_key=e.get("SUPABASE_SERVICE_KEY", "").strip(),
            supabase_anon_key=e.get("SUPABASE_ANON_KEY", "").strip(),
            retention_days=_i(e, "RETENTION_DAYS", 30),
            trend=TrendParams(
                alpha_trending=_f(e, "TREND_ALPHA_TRENDING", 0.25),
                alpha_rising=_f(e, "TREND_ALPHA_RISING", 1.00),
                subscriber_floor=_i(e, "TREND_SUBSCRIBER_FLOOR", 1_000),
                rising_subscriber_max=_i(e, "RISING_SUBSCRIBER_MAX", 100_000),
            ),
        )

    def require_db_credentials(self) -> "Settings":
        if self.db_mode != "live":
            return self
        if not self.supabase_url:
            raise ValueError("SUPABASE_URL 이 필요합니다 (DB_MODE=live)")
        if not self.supabase_service_key:
            raise ValueError("SUPABASE_SERVICE_KEY 가 필요합니다 (DB_MODE=live)")
        return self

    def require_yt_credentials(self) -> "Settings":
        if self.yt_mode != "live":
            return self
        if not self.yt_api_key:
            raise ValueError("YT_API_KEY 가 필요합니다 (YT_MODE=live)")
        return self


# ---------------------------------------------------------------- 택소노미


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    weight: float = 1.0
    keywords: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    sort_order: int = 0
    discovery_queries: tuple[str, ...] = ()        # 채널 검색용 head 질의 (100u/회)
    discovery_queries_niche: tuple[str, ...] = ()  # 최근 인기영상 검색용 롱테일 질의 (100u/회)


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    keywords: tuple[str, ...] = ()
    origin_countries: tuple[str, ...] = ()


@dataclass(frozen=True)
class Taxonomy:
    categories: tuple[Category, ...]
    regions: tuple[Region, ...]
    region_strategy: str = "subject"
    region_fallback: str | None = "origin"

    def category(self, cid: str) -> Category:
        for c in self.categories:
            if c.id == cid:
                return c
        raise KeyError(f"알 수 없는 카테고리: {cid}")

    def region(self, rid: str) -> Region:
        for r in self.regions:
            if r.id == rid:
                return r
        raise KeyError(f"알 수 없는 지역: {rid}")


def load_taxonomy(path: Path | str | None = None) -> Taxonomy:
    p = Path(path) if path else DEFAULT_TAXONOMY
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    cats = []
    for i, raw in enumerate(data.get("categories") or []):
        cats.append(
            Category(
                id=raw["id"],
                name=raw["name"],
                weight=float(raw.get("weight", 1.0)),
                keywords=tuple(raw.get("keywords") or ()),
                exclude=tuple(raw.get("exclude") or ()),
                sort_order=i,
                discovery_queries=tuple(raw.get("discovery_queries") or ()),
                discovery_queries_niche=tuple(raw.get("discovery_queries_niche") or ()),
            )
        )

    axis = data.get("region_axis") or {}
    regions = [
        Region(
            id=raw["id"],
            name=raw["name"],
            keywords=tuple(raw.get("keywords") or ()),
            origin_countries=tuple(raw.get("origin_countries") or ()),
        )
        for raw in (axis.get("regions") or [])
    ]

    return Taxonomy(
        categories=tuple(cats),
        regions=tuple(regions),
        region_strategy=axis.get("strategy", "subject"),
        region_fallback=axis.get("fallback"),
    )


@dataclass(frozen=True)
class Seed:
    channel_id: str = ""
    handle: str = ""
    region: str | None = None
    note: str = ""

    @property
    def is_resolved(self) -> bool:
        return bool(self.channel_id)


def load_seeds(path: Path | str | None = None) -> dict[str, list[Seed]]:
    p = Path(path) if path else DEFAULT_SEEDS
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out: dict[str, list[Seed]] = {}
    for cid, entries in (data.get("seeds") or {}).items():
        out[cid] = [
            Seed(
                channel_id=(e.get("channel_id") or "").strip(),
                handle=(e.get("handle") or "").strip(),
                region=e.get("region"),
                note=e.get("note", ""),
            )
            for e in (entries or [])
        ]
    return out
