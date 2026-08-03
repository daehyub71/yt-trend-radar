# -*- coding: utf-8 -*-
"""실제 Supabase 를 건드리는 테스트 — 기본 게이트에서 제외된다.

실행: pytest -m live      (CI 에서는 돌리지 않는다)
"""
import pytest

from core.config import Settings, load_taxonomy
from core.db import SupabaseRestDB, get_db

pytestmark = pytest.mark.live


@pytest.fixture
def live_db():
    s = Settings.from_env()
    if s.db_mode != "live" or not s.supabase_url:
        pytest.skip("DB_MODE=live 및 SUPABASE_* 설정이 필요합니다")
    return get_db(s)


def test_db_live_is_rest_client(live_db):
    assert isinstance(live_db, SupabaseRestDB)


def test_db_live_ping(live_db):
    assert live_db.ping() is True


def test_db_live_categories_match_yaml(live_db):
    """sync_config 로 반영된 DB 카테고리가 YAML 과 일치해야 한다."""
    tax = load_taxonomy()
    assert live_db.fetch_category_ids() == [c.id for c in tax.categories]


def test_db_live_regions_match_yaml(live_db):
    tax = load_taxonomy()
    assert sorted(live_db.fetch_region_ids()) == sorted(r.id for r in tax.regions)
