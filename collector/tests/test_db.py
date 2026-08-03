# -*- coding: utf-8 -*-
"""core.db — harness DB 왕복 및 팩토리 (P0)."""
import pytest

from core.config import Settings, load_taxonomy
from core.db import InMemoryDB, get_db


def test_db_factory_returns_inmemory_in_harness_mode():
    db = get_db(Settings.from_env())
    assert isinstance(db, InMemoryDB)


def test_db_factory_live_mode_requires_url(monkeypatch):
    monkeypatch.setenv("DB_MODE", "live")
    with pytest.raises(ValueError):
        get_db(Settings.from_env())


def test_db_ping_succeeds_in_harness():
    assert get_db(Settings.from_env()).ping() is True


def test_db_upsert_categories_roundtrip(config_dir):
    tax = load_taxonomy(config_dir / "categories.yaml")
    db = get_db(Settings.from_env())
    n = db.upsert_categories(tax.categories)
    assert n == len(tax.categories)
    # YAML 정의 순서가 보존돼야 한다 (웹의 카테고리 탭 순서가 여기서 나온다)
    assert db.fetch_category_ids() == [c.id for c in tax.categories]


def test_db_upsert_categories_is_idempotent(config_dir):
    tax = load_taxonomy(config_dir / "categories.yaml")
    db = get_db(Settings.from_env())
    db.upsert_categories(tax.categories)
    db.upsert_categories(tax.categories)
    assert len(db.fetch_category_ids()) == len(tax.categories)


def test_db_upsert_regions_roundtrip(config_dir):
    tax = load_taxonomy(config_dir / "categories.yaml")
    db = get_db(Settings.from_env())
    n = db.upsert_regions(tax.regions)
    assert n == 2
    assert db.fetch_region_ids() == ["domestic", "overseas"]


def test_db_tables_all_use_ytr_prefix():
    """이 Supabase 프로젝트는 다른 앱과 공유된다 — 접두어 없는 테이블명 금지."""
    from core.db import TABLES

    assert TABLES, "TABLES 가 비어 있다"
    for logical, physical in TABLES.items():
        assert physical.startswith("ytr_"), f"{logical} -> {physical} 접두어 누락"
