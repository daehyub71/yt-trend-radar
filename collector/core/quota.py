# -*- coding: utf-8 -*-
"""일 쿼터 회계와 안전장치 (SPEC NFR-4).

YouTube Data API v3 는 프로젝트당 하루 10,000 units 이고 추가 구매가 불가능하다.
search.list 가 100 units 로 압도적으로 비싸기 때문에 이 프로젝트의 수집 전략
(RSS 로 감지 + 50개 배치로 통계 조회 + search 는 예산제)이 성립한다.

쿼터가 바닥나도 서비스가 죽으면 안 된다 — 수집만 멈추고 서빙은 자체 DB 로 계속된다.
"""
from collections import defaultdict

# 실측 기준 (2026-07). videos.insert 는 2025-12 에 1600 → 100 으로 인하되었으나
# 이 프로젝트는 업로드를 하지 않으므로 조회 계열만 쓴다.
COSTS: dict[str, int] = {
    "videos.list": 1,
    "channels.list": 1,
    "playlistItems.list": 1,
    "search.list": 100,
}

MAX_IDS_PER_CALL = 50  # id 파라미터의 배치 상한 — 1 unit 으로 50개를 조회한다


class QuotaExceeded(RuntimeError):
    """일 예산을 넘는 호출이 시도됨. 호출자는 수집을 중단하고 정상 종료해야 한다."""


class QuotaLedger:
    def __init__(self, limit: int = 9_500, search_budget_calls: int | None = None) -> None:
        self.limit = limit
        self.search_budget_calls = search_budget_calls
        self.units: dict[str, int] = defaultdict(int)
        self.calls: dict[str, int] = defaultdict(int)

    # -- 상태 ---------------------------------------------------------
    @property
    def spent(self) -> int:
        return sum(self.units.values())

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.spent)

    def cost(self, endpoint: str) -> int:
        return COSTS[endpoint]  # 알 수 없는 엔드포인트는 KeyError — 조용히 넘기지 않는다

    def can_afford(self, endpoint: str) -> bool:
        if self.spent + self.cost(endpoint) > self.limit:
            return False
        if (
            endpoint == "search.list"
            and self.search_budget_calls is not None
            and self.calls[endpoint] >= self.search_budget_calls
        ):
            return False
        return True

    # -- 집행 ---------------------------------------------------------
    def charge(self, endpoint: str) -> None:
        cost = self.cost(endpoint)
        if (
            endpoint == "search.list"
            and self.search_budget_calls is not None
            and self.calls[endpoint] >= self.search_budget_calls
        ):
            raise QuotaExceeded(
                f"search 호출 예산 초과: {self.calls[endpoint]}/{self.search_budget_calls}회"
            )
        if self.spent + cost > self.limit:
            raise QuotaExceeded(
                f"일 쿼터 초과: {self.spent}+{cost} > {self.limit} ({endpoint})"
            )
        self.units[endpoint] += cost
        self.calls[endpoint] += 1

    def summary(self) -> str:
        parts = [f"{ep}={self.calls[ep]}회/{self.units[ep]}u" for ep in sorted(self.calls)]
        return f"{self.spent}/{self.limit} units" + (f" [{', '.join(parts)}]" if parts else "")

    @classmethod
    def from_settings(cls, settings) -> "QuotaLedger":
        return cls(
            limit=settings.yt_daily_quota_limit,
            search_budget_calls=settings.yt_search_budget_calls,
        )


def chunked(items: list, size: int = MAX_IDS_PER_CALL):
    """id 목록을 배치 단위로 자른다."""
    for i in range(0, len(items), size):
        yield items[i : i + size]
