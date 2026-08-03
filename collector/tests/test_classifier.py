# -*- coding: utf-8 -*-
"""engine.classifier — 키워드 기반 카테고리 분류 (P3).

배경: 시드 발굴이 '영상 1건이 질의에 맞으면 채널 채택' 이었다. 그래서 시사 채널
      (어쩌다시사)이 편의점 관련 영상 하나로 food 에 들어왔다. 채널은 **최근 영상 전체**로
      판정해야 한다.
"""
import pytest

from core.config import load_taxonomy
from engine.classifier import ChannelVerdict, classify_channel, classify_text, keyword_hits


@pytest.fixture
def tax(config_dir):
    return load_taxonomy(config_dir / "categories.yaml")


# ---------------------------------------------------------------- 키워드 매칭


def test_classifier_matches_multichar_korean_substring(tax):
    assert "먹방" in keyword_hits("오늘도 먹방 갑니다", tax.category("food"))


def test_classifier_single_char_keyword_needs_boundary(tax):
    """'회'(회 요리)가 '회사'·'기회'에 걸리면 오분류가 쏟아진다."""
    food = tax.category("food")
    assert "회" in keyword_hits("광어 회 한 접시", food)
    assert "회" not in keyword_hits("회사 점심 시간", food)
    assert "회" not in keyword_hits("좋은 기회였다", food)


def test_classifier_ascii_keyword_uses_word_boundary(tax):
    ai = tax.category("aicoding")
    assert "GPT" in keyword_hits("GPT 활용법", ai)
    assert "MCP" in keyword_hits("MCP 서버 만들기", ai)


def test_classifier_is_case_insensitive_for_ascii(tax):
    assert "vibe coding" in keyword_hits("Vibe Coding 실전", tax.category("aicoding"))


def test_classifier_exclude_blocks_category(tax):
    """exclude 에 걸리면 그 카테고리 점수는 0 이다."""
    assert classify_text("바이브코딩 스마트폰 리뷰", tax)[0] != "tech"


# ---------------------------------------------------------------- 텍스트 분류


def test_classifier_picks_highest_scoring_category(tax):
    cid, score = classify_text("제주 흑돼지 맛집 먹방 후기", tax)
    assert cid == "food"
    assert score > 0


def test_classifier_returns_none_for_unrelated_text(tax):
    cid, score = classify_text("국회 본회의 예산안 통과 브리핑", tax)
    assert cid is None
    assert score == 0


def test_classifier_aicoding_beats_tech_on_overlap(tax):
    """개발·AI 소재는 aicoding 소관 (가중치 1.1)."""
    assert classify_text("클로드 코드로 앱 개발하기", tax)[0] == "aicoding"


def test_classifier_vlog_loses_to_specific_category(tax):
    """브이로그는 포괄적이라 구체 카테고리에 밀려야 한다 (가중치 0.9)."""
    assert classify_text("자취 브이로그 오늘의 요리 레시피 먹방", tax)[0] == "food"


# ---------------------------------------------------------------- 채널 분류


def _titles_food():
    return [
        "제주 흑돼지 맛집 3곳",
        "편의점 신상 먹방",
        "자취 요리 레시피 공개",
        "동네 맛집 리뷰",
        "혼밥하기 좋은 식당",
    ]


def _titles_news():
    return [
        "이번 주 국회 브리핑",
        "환율 급등의 배경",
        "부동산 정책 정리",
        "편의점 신상이 알려주는 물가",  # 질의에 걸린 그 한 건
        "총선 판세 분석",
    ]


def test_classifier_channel_accepts_consistent_channel(tax):
    v = classify_channel(_titles_food(), tax)
    assert isinstance(v, ChannelVerdict)
    assert v.category_id == "food"
    assert v.matched >= 4
    assert v.hit_rate > 0.5


def test_classifier_channel_rejects_single_match_channel(tax):
    """영상 1건만 걸린 채널은 그 카테고리가 아니다 — 이번 사고의 핵심."""
    v = classify_channel(_titles_news(), tax)
    assert v.hit_rate <= 0.25
    assert v.accepts("food", min_hit_rate=0.3) is False


def test_classifier_channel_accepts_requires_matching_category(tax):
    v = classify_channel(_titles_food(), tax)
    assert v.accepts("food", min_hit_rate=0.3) is True
    assert v.accepts("travel", min_hit_rate=0.3) is False


def test_classifier_channel_empty_titles_is_undecided(tax):
    v = classify_channel([], tax)
    assert v.category_id is None
    assert v.hit_rate == 0
    assert v.accepts("food") is False


def test_classifier_channel_reports_sample_titles(tax):
    """검토 화면에 근거를 보여주기 위해 매칭된 제목을 남긴다."""
    v = classify_channel(_titles_food(), tax)
    assert v.samples
    assert all(isinstance(t, str) for t in v.samples)
    assert len(v.samples) <= 3


def test_classifier_channel_counts_distribution(tax):
    v = classify_channel(_titles_food() + ["유럽 배낭여행 코스"], tax)
    assert v.distribution["food"] >= 4
    assert v.distribution.get("travel") == 1


# ---------------------------------------------------------------- 실측 회귀
# 아래는 2026-07-30 RSS 실검증에서 나온 **실제 영상 제목**이다.
# 분류기 결함으로 정당한 음식 채널이 탈락하고, 시사·썰 채널이 통과하려 했다.


@pytest.mark.parametrize(
    "title",
    [
        "계속 찾게 되는 오뚜기 라면 TOP3 (+돈쭐나는 이유)",       # 득템
        "맛집들 긴장하게 하는 냉동식품 TOP3",                    # 득템
        "요즘 꽂혀버린 초간단 밥도둑 치트키 ㄷㄷ",                 # 득템
        "국수처럼 떠먹기 좋은 어묵볶음",                         # cho.eat
        "중복날 삼계탕 레시피 찾고 계신가요?",                    # cho.eat
        "차갑게 먹는 게 묘미인 파스타 밀프랩",                    # cho.eat
    ],
)
def test_classifier_real_food_titles_classify_as_food(tax, title):
    assert classify_text(title, tax)[0] == "food", f"음식으로 잡혀야 한다: {title}"


@pytest.mark.parametrize(
    "title",
    [
        "요즘 소주가 왜이리 힙해ㅣ[톡! 까놓고 신상리뷰]",          # CU — tech 가 '리뷰'로 훔쳐갔다
        "웨이팅 없이 빵지순례 가능? 어 가능",                     # CU
    ],
)
def test_classifier_generic_review_words_do_not_mean_tech(tax, title):
    """'리뷰'·'언박싱'은 모든 카테고리에 쓰이는 일반어 — tech 정체성을 실을 수 없다."""
    assert classify_text(title, tax)[0] != "tech", f"tech 가 아니어야 한다: {title}"


@pytest.mark.parametrize(
    "title",
    [
        "퇴사",                                              # 나쵸썰 (사연·썰)
        "시어머니",
        "이혼해!",
        "당선 무효형 받고도 오세훈이 우기는 이유",                 # 어쩌다시사
        "한국에서 돈벌어 미국 로비로 압박하는 쿠팡",
        "로맨스 스캠도 사랑이다",                               # 우끼자나
        "문구점 슬랑이 종류별로 다 만져보기",                     # 다람냥 (슬라임)
    ],
)
def test_classifier_offtopic_titles_stay_unclassified(tax, title):
    """어떤 카테고리에도 들어가면 안 되는 제목 — 미분류가 정답이다."""
    assert classify_text(title, tax)[0] is None, f"미분류여야 한다: {title}"


@pytest.mark.parametrize(
    "title,expected",
    [
        # food 키워드를 대폭 늘린 직후, 아래 제목들이 전부 food 로 넘어갔다 (실측 회귀).
        ("싱그러운 여름비와 함께하는 경차 차박 | 캠핑 음식! | 강화도 아르보리아캠핑장", "travel"),
        ("가족들과 함께하는 2박 3일 힐링 캠프 | 먹은 게 너무 많아서 셀 수가 없음 | 마리원캠핑장", "travel"),
        ("한여름 여긴 딴 세상! 3년연속 이곳을 여름휴가 여행지로 다녀온 이유", "travel"),
        ("사람들이 모르는 휴게소 비밀공간! 휴게소 차박 이건 꼭 알아야 함!", "travel"),
        ("vlog 소소하고 부지런한 삼시세끼 오이에 또 빠짐, 숨가쁜 육아", "vlog"),
        # 등산 채널은 '등산'이라는 단어를 쓰지 않는다
        ("지리산 칠선 계곡 / 가장 빡세고 험한 원시림 / 한정판 지리산 코스", "fitness"),
        ("100대명산 완등하며 알게 된 여름 산행이 힘든 이유 7가지!", "fitness"),
        ("북한산 가장 빠른 코스는? 백운대 최단코스 가이드", "fitness"),
        # 영어 제목 피트니스 채널
        ("15 MIN COOLDOWN STRETCHING ROUTINE AFTER WORKOUT", "fitness"),
        ("10 MIN DANCE PARTY - WEIGHT LOSS WORKOUT", "fitness"),
    ],
)
def test_classifier_category_ownership_regression(tax, title, expected):
    assert classify_text(title, tax)[0] == expected, f"{expected} 여야 한다: {title}"


def test_classifier_hit_count_is_capped(tax):
    """키워드를 많이 가진 카테고리가 언급 횟수로 이기면 안 된다.

    상한이 없으면 food(키워드 48개)가 travel(19개)을 언제나 이긴다 — 실제로 그랬다.
    """
    from engine.classifier import MAX_COUNTED_HITS, score_text

    many = "먹방 맛집 요리 레시피 라면 치킨 김치 파스타"  # food 키워드 8개
    s = score_text(many, tax.category("food"))
    assert s == MAX_COUNTED_HITS * tax.category("food").weight


def test_classifier_rejects_storytelling_channel(tax):
    """사연·썰 채널은 어떤 카테고리도 채택하지 못한다."""
    v = classify_channel(["퇴사", "시어머니", "이혼해!", "호상?", "어쩌라고..?"], tax)
    assert v.category_id is None
    assert v.accepts("food") is False


def test_classifier_accepts_recipe_channel_after_keyword_fix(tax):
    """cho.eat 유형 — 구체 음식명만 쓰는 요리 채널도 통과해야 한다."""
    v = classify_channel(
        [
            "국수처럼 떠먹기 좋은 어묵볶음",
            "어렵게 느낄 필요 전혀 없는 오징어볶음",
            "차갑게 먹는 게 묘미인 파스타 밀프랩",
            "중복날 삼계탕 레시피 찾고 계신가요?",
            "간단 한끼 찾으시는 분 여기예요",
        ],
        tax,
    )
    assert v.accepts("food", min_hit_rate=0.3) is True
