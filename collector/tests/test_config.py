# -*- coding: utf-8 -*-
"""core.config — 설정/택소노미 로딩 (P0)."""
import pytest

from core.config import Settings, load_seeds, load_taxonomy


def test_config_from_env_defaults_to_harness():
    s = Settings.from_env()
    assert s.yt_mode == "harness"
    assert s.db_mode == "harness"
    assert s.is_harness is True


def test_config_from_env_reads_trend_params(monkeypatch):
    monkeypatch.setenv("TREND_ALPHA_TRENDING", "0.4")
    monkeypatch.setenv("TREND_ALPHA_RISING", "1.2")
    monkeypatch.setenv("TREND_SUBSCRIBER_FLOOR", "2000")
    monkeypatch.setenv("RISING_SUBSCRIBER_MAX", "50000")
    monkeypatch.setenv("RETENTION_DAYS", "30")
    s = Settings.from_env()
    assert s.trend.alpha_trending == pytest.approx(0.4)
    assert s.trend.alpha_rising == pytest.approx(1.2)
    assert s.trend.subscriber_floor == 2000
    assert s.trend.rising_subscriber_max == 50000
    assert s.retention_days == 30


def test_config_rising_alpha_exceeds_trending_alpha():
    """신규 발굴(rising)은 구독자 규모를 더 강하게 정규화해야 한다 (SPEC FR-7)."""
    s = Settings.from_env()
    assert s.trend.alpha_rising > s.trend.alpha_trending


def test_config_rising_alpha_meets_absolute_floor():
    """'trending 보다 크다'만으로는 부족하다 — 0.75 > 0.35 도 그 조건은 만족하지만
    보드는 여전히 구독자 규모 순이 된다 (2026-08-03 실증). 절대 하한 1.0 을 함께 본다."""
    assert Settings.from_env().trend.alpha_rising >= 1.0


def test_config_env_file_values_are_valid(monkeypatch):
    """실제 .env / .env.example 에 담긴 값이 규약을 지키는지 확인한다.

    죽은 설정이던 시절 .env 에는 규약 위반값(0.75)이 들어 있었다.
    """
    from pathlib import Path

    from core.config import PROJECT_ROOT

    for name in (".env", ".env.example"):
        p = Path(PROJECT_ROOT) / name
        if not p.exists():
            continue
        env = {}
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
        if "TREND_ALPHA_RISING" in env:
            assert float(env["TREND_ALPHA_RISING"]) >= 1.0, f"{name} 의 rising α 가 규약 위반"


def test_config_live_mode_requires_credentials(monkeypatch):
    monkeypatch.setenv("DB_MODE", "live")
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        Settings.from_env().require_db_credentials()


EXPECTED_CATEGORIES = ["food", "travel", "tech", "aicoding", "vlog", "fitness"]


def test_taxonomy_loads_expected_categories(config_dir):
    tax = load_taxonomy(config_dir / "categories.yaml")
    assert [c.id for c in tax.categories] == EXPECTED_CATEGORIES
    assert tax.category("food").name == "음식"
    assert tax.category("aicoding").name == "바이브코딩·AI"


def test_taxonomy_aicoding_outranks_tech(config_dir):
    """AI·코딩 소재는 tech 가 아니라 aicoding 으로 가야 한다 (가중치로 보장)."""
    tax = load_taxonomy(config_dir / "categories.yaml")
    assert tax.category("aicoding").weight > tax.category("tech").weight


def test_taxonomy_tech_does_not_claim_ai_keywords(config_dir):
    """tech 키워드에 개발/코딩/AI 가 남아 있으면 aicoding 콘텐츠를 흡수한다."""
    tech_kw = {k.lower() for k in tax_category(config_dir, "tech").keywords}
    for owned in ("개발", "코딩", "프로그래밍", "ai", "인공지능"):
        assert owned not in tech_kw, f"tech 가 '{owned}' 를 아직 갖고 있다"


def tax_category(config_dir, cid):
    return load_taxonomy(config_dir / "categories.yaml").category(cid)


def test_taxonomy_loads_two_regions(config_dir):
    tax = load_taxonomy(config_dir / "categories.yaml")
    assert [r.id for r in tax.regions] == ["domestic", "overseas"]
    assert tax.region("domestic").name == "국내"
    assert "KR" in tax.region("domestic").origin_countries


def test_taxonomy_every_category_has_keywords(config_dir):
    tax = load_taxonomy(config_dir / "categories.yaml")
    for c in tax.categories:
        assert c.keywords, f"{c.id} 에 keywords 가 없다"


def test_taxonomy_vlog_weight_is_lowest(config_dir):
    """브이로그는 가장 포괄적이라 다른 카테고리에 밀려야 한다 (categories.yaml 주석)."""
    tax = load_taxonomy(config_dir / "categories.yaml")
    vlog = tax.category("vlog")
    assert all(vlog.weight <= c.weight for c in tax.categories)


def test_taxonomy_region_strategy_is_declared(config_dir):
    tax = load_taxonomy(config_dir / "categories.yaml")
    assert tax.region_strategy in ("subject", "origin")
    assert tax.region_fallback in ("subject", "origin", None)


def test_taxonomy_yaml_has_no_duplicate_keys(config_dir):
    """PyYAML 은 중복 키를 조용히 덮어쓴다 — 편집 사고로 남의 질의를 쓰게 된 적이 있다.

    실제 사고(2026-07-30): aicoding 추가 시 tech 의 discovery_queries 두 줄이 aicoding
    블록으로 밀려 들어가 중복 키가 됐고, 나중 값이 이겨서 aicoding 이 tech 질의로 발굴됐다.
    """
    import yaml

    class StrictLoader(yaml.SafeLoader):
        pass

    def _no_duplicates(loader, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in mapping:
                raise AssertionError(f"categories.yaml 중복 키: {key!r}")
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    StrictLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates
    )
    yaml.load((config_dir / "categories.yaml").read_text(encoding="utf-8"), Loader=StrictLoader)


def test_taxonomy_discovery_queries_are_unique_per_category(config_dir):
    """두 카테고리가 같은 질의 묶음을 쓰면 같은 채널만 발굴된다 (중복 키 사고의 증상)."""
    tax = load_taxonomy(config_dir / "categories.yaml")
    seen: dict[tuple[str, ...], str] = {}
    for c in tax.categories:
        for label, queries in (("head", c.discovery_queries), ("niche", c.discovery_queries_niche)):
            if not queries:
                continue
            key = tuple(queries)
            assert key not in seen, f"{c.id}.{label} 질의가 {seen[key]} 와 동일하다"
            seen[key] = f"{c.id}.{label}"


def test_taxonomy_every_category_has_discovery_queries(config_dir):
    tax = load_taxonomy(config_dir / "categories.yaml")
    for c in tax.categories:
        assert c.discovery_queries, f"{c.id} 에 discovery_queries 가 없다"
        assert c.discovery_queries_niche, f"{c.id} 에 discovery_queries_niche 가 없다"


def test_taxonomy_unknown_category_raises(config_dir):
    tax = load_taxonomy(config_dir / "categories.yaml")
    with pytest.raises(KeyError):
        tax.category("nope")


def test_seeds_covers_every_category(config_dir):
    """카테고리를 추가하면 시드도 채워야 한다 — 빈 버킷은 그 카테고리 보드가 빈다는 뜻."""
    seeds = load_seeds(config_dir / "seeds.yaml")
    assert set(seeds) == set(EXPECTED_CATEGORIES)
    assert all(isinstance(v, list) for v in seeds.values())


def test_seeds_channel_ids_are_real_format(config_dir):
    """channel_id 는 추측 금지 — UC + 22자 형태여야 한다."""
    seeds = load_seeds(config_dir / "seeds.yaml")
    for cid, entries in seeds.items():
        for s in entries:
            assert s.channel_id.startswith("UC") and len(s.channel_id) == 24, (
                f"{cid}: 잘못된 channel_id {s.channel_id!r}"
            )
