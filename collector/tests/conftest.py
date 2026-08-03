# -*- coding: utf-8 -*-
import os
import sys
from pathlib import Path

import pytest

COLLECTOR = Path(__file__).resolve().parent.parent
PROJECT = COLLECTOR.parent
sys.path.insert(0, str(COLLECTOR))


@pytest.fixture(autouse=True)
def _harness_env(request, monkeypatch):
    """기본 테스트는 외부 의존성 없이 돈다 (Harness Engineering 규칙).

    .env 가 있어도 테스트가 실서버를 건드리지 않도록 모드를 강제한다.
    @pytest.mark.live 가 붙은 테스트만 .env 를 읽어 실제 자원에 접근한다.
    """
    if request.node.get_closest_marker("live"):
        from dotenv import load_dotenv

        load_dotenv(PROJECT / ".env", override=False)
        yield
        return

    monkeypatch.setenv("YT_MODE", "harness")
    monkeypatch.setenv("DB_MODE", "harness")
    for k in ("YT_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_ANON_KEY"):
        monkeypatch.delenv(k, raising=False)
    yield


@pytest.fixture
def project_root() -> Path:
    return PROJECT


@pytest.fixture
def config_dir(project_root) -> Path:
    return project_root / "config"
