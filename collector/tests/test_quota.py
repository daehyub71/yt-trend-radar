# -*- coding: utf-8 -*-
"""core.quota — 일 쿼터 안전장치 (SPEC NFR-4)."""
import pytest

from core.quota import COSTS, QuotaExceeded, QuotaLedger


def test_quota_costs_match_youtube_pricing():
    """search.list 가 100배 비싸다는 사실이 설계 전체의 근거다."""
    assert COSTS["videos.list"] == 1
    assert COSTS["channels.list"] == 1
    assert COSTS["search.list"] == 100


def test_quota_ledger_charges_units():
    q = QuotaLedger(limit=100)
    q.charge("videos.list")
    q.charge("channels.list")
    assert q.spent == 2
    assert q.remaining == 98


def test_quota_ledger_tracks_calls_per_endpoint():
    q = QuotaLedger(limit=1000)
    q.charge("videos.list")
    q.charge("videos.list")
    q.charge("search.list")
    assert q.calls["videos.list"] == 2
    assert q.units["search.list"] == 100


def test_quota_ledger_blocks_when_over_limit():
    q = QuotaLedger(limit=150)
    q.charge("search.list")  # 100
    with pytest.raises(QuotaExceeded):
        q.charge("search.list")  # 200 > 150
    assert q.spent == 100, "차단된 호출은 소모로 계상하지 않는다"


def test_quota_ledger_can_afford():
    q = QuotaLedger(limit=100)
    assert q.can_afford("search.list") is True
    q.charge("videos.list")
    assert q.can_afford("search.list") is False  # 1 + 100 > 100


def test_quota_ledger_search_budget_limits_calls():
    """search 는 유닛과 별개로 호출 횟수 예산도 갖는다 (SPEC FR-6)."""
    q = QuotaLedger(limit=100_000, search_budget_calls=2)
    q.charge("search.list")
    q.charge("search.list")
    assert q.can_afford("search.list") is False
    with pytest.raises(QuotaExceeded, match="search"):
        q.charge("search.list")


def test_quota_ledger_unknown_endpoint_raises():
    q = QuotaLedger(limit=100)
    with pytest.raises(KeyError):
        q.charge("playlistItems.insert")
