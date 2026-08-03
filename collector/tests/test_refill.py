# -*- coding: utf-8 -*-
"""jobs.refill_seeds 의 결손 계산 — 순수 로직."""
from jobs.bootstrap_seeds import DEFAULT_QUOTAS
from jobs.refill_seeds import compute_deficit


def _e(tier: str) -> dict:
    return {"channel_id": "UC" + "x" * 22, "note": f"채널 · 구독자 1,000 [{tier}]"}


def test_refill_deficit_when_empty():
    assert compute_deficit([], DEFAULT_QUOTAS) == DEFAULT_QUOTAS


def test_refill_deficit_when_full():
    kept = [_e(t) for t, n in DEFAULT_QUOTAS.items() for _ in range(n)]
    assert sum(compute_deficit(kept, DEFAULT_QUOTAS).values()) == 0


def test_refill_deficit_counts_per_tier():
    kept = [_e("micro"), _e("micro"), _e("large")]
    d = compute_deficit(kept, DEFAULT_QUOTAS)
    assert d["micro"] == DEFAULT_QUOTAS["micro"] - 2
    assert d["large"] == DEFAULT_QUOTAS["large"] - 1
    assert d["small"] == DEFAULT_QUOTAS["small"]


def test_refill_deficit_does_not_go_negative():
    """어떤 티어가 초과여도 음수 결손을 만들지 않는다 (다른 티어로 이월도 하지 않는다)."""
    kept = [_e("large")] * 10
    d = compute_deficit(kept, DEFAULT_QUOTAS)
    assert d["large"] == 0
    assert d["micro"] == DEFAULT_QUOTAS["micro"]


def test_refill_deficit_ignores_entries_without_tier():
    kept = [{"channel_id": "UCzz", "note": "구간 표기 없음"}]
    assert compute_deficit(kept, DEFAULT_QUOTAS) == DEFAULT_QUOTAS
