# -*- coding: utf-8 -*-
"""jobs.bootstrap_seeds 의 층화 추출 — 순수 로직 (외부 호출 없음).

배경: 초기 부트스트랩이 '구독자 내림차순 상위 N'을 뽑아 대형 채널만 남았다.
      그러면 rising 보드(구독자 10만 이하 대상)가 텅 빈다 — 추적 풀이 곧 발굴 한계다.
      따라서 구간별 쿼터로 뽑는다.
"""
import pytest

from jobs.bootstrap_seeds import (
    DEFAULT_QUOTAS,
    TIERS,
    count_under_100k,
    entry_tier,
    looks_korean,
    render_seeds_yaml,
    select_stratified,
    tier_of,
)


def _ch(cid: str, subs: int) -> dict:
    return {"channel_id": cid, "title": f"ch{cid}", "handle": "", "subscriber_count": subs}


# ---------------------------------------------------------------- 구간 판정


@pytest.mark.parametrize(
    "subs,expected",
    [
        (1_000, "micro"),
        (9_999, "micro"),
        (10_000, "small"),
        (99_999, "small"),
        (100_000, "mid"),
        (999_999, "mid"),
        (1_000_000, "large"),
        (16_800_000, "large"),
    ],
)
def test_seed_tier_of(subs, expected):
    assert tier_of(subs) == expected


def test_seed_tiers_cover_rising_threshold():
    """rising 대상(구독자 10만 이하)은 micro+small 구간이다 — SPEC D7 과 정합해야 한다."""
    assert TIERS["micro"][1] == 10_000
    assert TIERS["small"][1] == 100_000


def test_seed_tier_of_none_is_unknown():
    assert tier_of(None) is None


# ---------------------------------------------------------------- 층화 추출


def test_seed_selection_respects_tier_quotas():
    rows = (
        [_ch(f"m{i}", 5_000) for i in range(10)]
        + [_ch(f"s{i}", 50_000) for i in range(10)]
        + [_ch(f"d{i}", 500_000) for i in range(10)]
        + [_ch(f"L{i}", 5_000_000) for i in range(10)]
    )
    quotas = {"micro": 4, "small": 5, "mid": 4, "large": 2}
    got = select_stratified(rows, quotas)
    counts = {t: sum(1 for r in got if tier_of(r["subscriber_count"]) == t) for t in TIERS}
    assert counts == quotas
    assert len(got) == 15


def test_seed_selection_prefers_small_channels_overall():
    """총량의 과반이 10만 이하여야 한다 — rising 발굴이 이 풀에서 나온다."""
    rows = (
        [_ch(f"m{i}", 3_000) for i in range(20)]
        + [_ch(f"s{i}", 40_000) for i in range(20)]
        + [_ch(f"d{i}", 300_000) for i in range(20)]
        + [_ch(f"L{i}", 2_000_000) for i in range(20)]
    )
    got = select_stratified(rows, {"micro": 4, "small": 5, "mid": 4, "large": 2})
    under_100k = sum(1 for r in got if (r["subscriber_count"] or 0) < 100_000)
    assert under_100k > len(got) / 2


def test_seed_selection_backfills_when_tier_is_short():
    """어떤 구간에 후보가 부족하면 남은 자리를 다른 구간에서 채운다 (총량 유지)."""
    rows = [_ch(f"m{i}", 5_000) for i in range(2)] + [_ch(f"s{i}", 50_000) for i in range(20)]
    got = select_stratified(rows, {"micro": 4, "small": 5, "mid": 4, "large": 2})
    assert len(got) == 15
    assert sum(1 for r in got if tier_of(r["subscriber_count"]) == "micro") == 2


def test_seed_selection_within_tier_is_subscriber_desc():
    rows = [_ch("a", 9_000), _ch("b", 3_000), _ch("c", 7_000)]
    got = select_stratified(rows, {"micro": 2, "small": 0, "mid": 0, "large": 0})
    assert [r["channel_id"] for r in got] == ["a", "c"]


def test_seed_selection_drops_unknown_subscriber_counts():
    rows = [_ch("a", 5_000), {"channel_id": "x", "title": "x", "subscriber_count": None}]
    got = select_stratified(rows, {"micro": 4, "small": 0, "mid": 0, "large": 0})
    assert [r["channel_id"] for r in got] == ["a"]


def test_seed_selection_deduplicates_by_channel_id():
    rows = [_ch("a", 5_000), _ch("a", 5_000), _ch("b", 6_000)]
    got = select_stratified(rows, {"micro": 4, "small": 0, "mid": 0, "large": 0})
    assert [r["channel_id"] for r in got] == ["b", "a"]


def test_seed_selection_empty_input():
    assert select_stratified([], {"micro": 4, "small": 5, "mid": 4, "large": 2}) == []


# ---------------------------------------------------------------- 한국어 판정
# 실측: aicoding 카테고리 첫 발굴에서 15개 중 9개가 영어권이었다
# (freeCodeCamp 1,180만 / CBC News 471만 등). AI·코딩은 영어권 비중이 압도적이라
# relevanceLanguage=ko 만으로는 카테고리가 성립하지 않는다.


def test_seed_looks_korean_by_country_code():
    assert looks_korean(title="UNDERkg", country="KR") is True
    assert looks_korean(title="freeCodeCamp.org", country="US") is False


def test_seed_looks_korean_by_hangul_in_title():
    assert looks_korean(title="조코딩 JoCoding") is True
    assert looks_korean(title="하울 바이브 코딩") is True
    assert looks_korean(title="Caleb Writes Code") is False


def test_seed_looks_korean_by_hangul_in_description():
    """영문 채널명이어도 소개글이 한국어면 한국 채널로 본다."""
    assert looks_korean(title="SmartDaddy", description="AI 도구를 소개합니다") is True
    assert looks_korean(title="Matt Williams", description="Local LLM tutorials") is False


def test_seed_looks_korean_rejects_english_news():
    assert looks_korean(title="CBC News", description="Canadian news") is False


def test_seed_looks_korean_handles_empty_input():
    assert looks_korean() is False


# ---------------------------------------------------------------- 렌더링·병합
# 회귀: --only 병합 시 기존 항목에는 subscriber_count 가 없어 렌더러가 KeyError 로 죽었다.
# API 호출(700u)을 다 쓴 뒤 마지막 쓰기 단계에서 터져 결과가 유실됐으므로 테스트로 고정한다.


def test_seed_entry_tier_from_subscriber_count():
    assert entry_tier({"subscriber_count": 5_000}) == "micro"
    assert entry_tier({"subscriber_count": 2_000_000}) == "large"


def test_seed_entry_tier_falls_back_to_note():
    """병합된 기존 항목은 note 의 [tier] 표기에서 구간을 읽어야 한다."""
    assert entry_tier({"note": "어떤채널 · 구독자 8,650 [micro]"}) == "micro"
    assert entry_tier({"note": "큰채널 · 구독자 3,300,000 [large]"}) == "large"
    assert entry_tier({"note": "표기없음"}) is None


def test_seed_render_accepts_merged_entries_without_stats():
    """subscriber_count 없는 병합 항목과 새 항목이 섞여도 렌더링돼야 한다."""
    found = {
        "food": [{"channel_id": "UC" + "a" * 22, "handle": "@old", "note": "기존 · 구독자 9,000 [micro]"}],
        "aicoding": [
            {"channel_id": "UC" + "b" * 22, "handle": "@new", "title": "신규", "subscriber_count": 50_000}
        ],
    }
    out = render_seeds_yaml(found, {}, {"micro": 4, "small": 5, "mid": 4, "large": 2})
    assert "기존 · 구독자 9,000 [micro]" in out, "기존 note 는 그대로 유지"
    assert "신규 · 구독자 50,000 [small]" in out, "새 항목은 note 를 생성"
    assert count_under_100k(found) == 2


def test_seed_render_output_is_valid_yaml():
    import yaml

    found = {
        "food": [{"channel_id": "UC" + "a" * 22, "handle": "@x", "note": 'quote " and \\ backslash'}]
    }
    parsed = yaml.safe_load(render_seeds_yaml(found, {}, DEFAULT_QUOTAS))
    assert parsed["seeds"]["food"][0]["note"] == 'quote " and \\ backslash'
