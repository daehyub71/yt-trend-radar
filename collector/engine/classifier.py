# -*- coding: utf-8 -*-
"""키워드 기반 카테고리 분류 (SPEC FR-1).

규칙은 `config/categories.yaml` 이 소유한다 — 이 모듈은 규칙을 해석할 뿐이다.

## 매칭 방식

한국어는 어절 경계가 없어 부분문자열 매칭이 기본이지만, **한 글자 키워드는 위험하다**:
food 의 `회`(회 요리)가 `회사`·`기회`·`본회의`에 걸린다. 그래서
  - 한 글자 한글 키워드: 앞뒤에 한글이 없을 때만 매칭
  - ASCII 키워드: 단어 경계(`\\b`) + 대소문자 무시
  - 그 외: 부분문자열

## 채널 판정

영상 1건이 걸렸다고 채널을 그 카테고리로 보면 안 된다 — 시사 채널이 편의점 관련 영상
하나로 food 에 들어온 실제 사고가 있었다. 채널은 **최근 영상 제목 전체**의 분포로 판정하고,
적중률(hit_rate)이 기준을 넘어야 채택한다.
"""
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

from core.config import Category, Taxonomy


@lru_cache(maxsize=4096)
def _pattern(keyword: str) -> re.Pattern:
    kw = keyword.strip()
    if not kw:
        return re.compile(r"(?!)")  # 절대 매칭되지 않음
    if kw.isascii():
        return re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
    if len(kw) == 1:
        # 한 글자 한글: 다른 한글에 붙어 있으면 다른 단어의 일부다
        return re.compile(rf"(?<![가-힣]){re.escape(kw)}(?![가-힣])")
    return re.compile(re.escape(kw), re.IGNORECASE)


def keyword_hits(text: str, category: Category) -> list[str]:
    """텍스트에서 매칭된 카테고리 키워드 목록 (중복 없음, 정의 순서)."""
    if not text:
        return []
    return [kw for kw in category.keywords if _pattern(kw).search(text)]


def is_excluded(text: str, category: Category) -> bool:
    return any(_pattern(kw).search(text) for kw in category.exclude)


# 한 제목에서 세는 히트 수의 상한.
# 상한이 없으면 **키워드를 많이 가진 카테고리가 무조건 이긴다**. 실제 사고(2026-07-30):
# food 키워드를 20여 개 보강한 직후, 캠핑 채널(조조캠핑)·육아 브이로그(트위티)·여행 채널
# (푸른아오)이 모두 food 로 넘어갔다. 음식 이야기가 한 제목에 여러 번 나오면 점수가 폭증하기
# 때문이다. 상한을 두면 "얼마나 많이 언급했나"가 아니라 "어느 주제가 걸렸나"로 경쟁한다.
MAX_COUNTED_HITS = 3


def score_text(text: str, category: Category) -> float:
    """카테고리 점수. exclude 에 걸리면 0. 히트 수는 MAX_COUNTED_HITS 로 상한."""
    if not text or is_excluded(text, category):
        return 0.0
    hits = keyword_hits(text, category)
    return min(len(hits), MAX_COUNTED_HITS) * category.weight if hits else 0.0


def classify_text(text: str, taxonomy: Taxonomy) -> tuple[str | None, float]:
    """가장 높은 점수의 카테고리. 무득점이면 (None, 0). 동점이면 정의 순서가 앞선 쪽."""
    best_id, best_score = None, 0.0
    for cat in taxonomy.categories:
        s = score_text(text, cat)
        if s > best_score:
            best_id, best_score = cat.id, s
    return best_id, best_score


@dataclass
class ChannelVerdict:
    """채널 단위 판정 결과."""

    category_id: str | None
    matched: int  # 우승 카테고리로 분류된 영상 수
    total: int  # 검사한 영상 수
    distribution: dict[str, int] = field(default_factory=dict)
    samples: list[str] = field(default_factory=list)  # 근거 제목 (최대 3)

    @property
    def hit_rate(self) -> float:
        return self.matched / self.total if self.total else 0.0

    @property
    def dominance(self) -> float:
        """매칭된 영상 중 우승 카테고리 비중 (다른 주제와 섞인 정도)."""
        total_matched = sum(self.distribution.values())
        return self.matched / total_matched if total_matched else 0.0

    def accepts(self, target_category: str, min_hit_rate: float = 0.3) -> bool:
        return self.category_id == target_category and self.hit_rate >= min_hit_rate


def classify_channel(titles: list[str], taxonomy: Taxonomy) -> ChannelVerdict:
    """최근 영상 제목들로 채널 카테고리를 판정한다."""
    titles = [t for t in titles if t and t.strip()]
    if not titles:
        return ChannelVerdict(category_id=None, matched=0, total=0)

    per_title: list[tuple[str, str]] = []  # (category_id, title)
    for t in titles:
        cid, _ = classify_text(t, taxonomy)
        if cid:
            per_title.append((cid, t))

    dist = Counter(cid for cid, _ in per_title)
    if not dist:
        return ChannelVerdict(category_id=None, matched=0, total=len(titles))

    # 동점이면 카테고리 정의 순서가 앞선 쪽 (Counter.most_common 은 순서 보장이 약하다)
    order = {c.id: i for i, c in enumerate(taxonomy.categories)}
    winner = min(dist, key=lambda cid: (-dist[cid], order.get(cid, 999)))

    return ChannelVerdict(
        category_id=winner,
        matched=dist[winner],
        total=len(titles),
        distribution=dict(dist),
        samples=[t for cid, t in per_title if cid == winner][:3],
    )
