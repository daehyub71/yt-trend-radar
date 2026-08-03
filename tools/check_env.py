# -*- coding: utf-8 -*-
"""환경 연결 점검 — 시크릿을 절대 출력하지 않는다 (워크스페이스 CLAUDE.md 규칙).

출력하는 것: 호스트, 키 존재 여부/길이, JWT role 클레임, HTTP 상태코드, 서버 에러 메시지.
출력하지 않는 것: 키 값, 비밀번호, 접속 문자열 전체.

사용법: python tools/check_env.py
"""
import base64
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collector"))


def load_env():
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")


def jwt_claims(token: str) -> dict:
    """JWT 페이로드만 디코드 (서명 검증 아님, 진단용). 실패 시 빈 dict."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def mask(name: str) -> str:
    v = os.environ.get(name, "")
    if not v:
        return f"  {name:28s} = (없음)"
    claims = jwt_claims(v)
    extra = ""
    if claims:
        extra = f", role={claims.get('role')}, exp={claims.get('exp')}"
    return f"  {name:28s} = 설정됨 (len={len(v)}{extra})"


def check_postgrest(label: str, key: str, url: str):
    import requests

    try:
        r = requests.get(
            f"{url}/rest/v1/",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=20,
        )
        body = (r.text or "")[:200].replace("\n", " ")
        detail = "" if r.ok else f" | {body}"
        print(f"  {label:28s} HTTP {r.status_code}{detail}")
        return r.ok
    except Exception as e:
        print(f"  {label:28s} ERROR {type(e).__name__}: {e}")
        return False


def check_postgres(db_url: str):
    """pg8000 으로 직접 접속 — 세션 모드(5432)를 우선 시도."""
    import ssl

    import pg8000.dbapi

    parts = urlsplit(db_url)
    from urllib.parse import unquote

    user = unquote(parts.username or "")
    password = unquote(parts.password or "")
    host = parts.hostname or ""
    database = (parts.path or "/postgres").lstrip("/") or "postgres"

    for port, mode in ((5432, "session"), (parts.port or 6543, "transaction")):
        try:
            conn = pg8000.dbapi.connect(
                user=user,
                password=password,
                host=host,
                port=port,
                database=database,
                ssl_context=ssl.create_default_context(),
                timeout=20,
            )
            cur = conn.cursor()
            cur.execute("select current_user, version()")
            row = cur.fetchone()
            cur.execute(
                "select count(*) from information_schema.tables where table_schema='public'"
            )
            n_tables = cur.fetchone()[0]
            conn.close()
            pg = row[1].split(" on ")[0] if row else "?"
            print(f"  postgres:{port} ({mode:11s}) OK  user={row[0]} | {pg} | public 테이블 {n_tables}개")
            return port
        except Exception as e:
            msg = str(e)[:180].replace("\n", " ")
            print(f"  postgres:{port} ({mode:11s}) FAIL {type(e).__name__}: {msg}")
    return None


def main():
    load_env()
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    print("=== 환경변수 ===")
    print(f"  {'SUPABASE_URL':28s} = {urlsplit(url).hostname or '(없음)'}")
    for k in ("SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY", "YT_API_KEY"):
        print(mask(k))
    dbu = os.environ.get("SUPABASE_DATABASE_URL", "")
    if dbu:
        p = urlsplit(dbu)
        print(f"  {'SUPABASE_DATABASE_URL':28s} = 설정됨 (host={p.hostname}, port={p.port})")
    print(f"  {'YT_MODE / DB_MODE':28s} = {os.environ.get('YT_MODE')} / {os.environ.get('DB_MODE')}")

    print("\n=== PostgREST (HTTP) ===")
    if url:
        check_postgrest("anon key", os.environ.get("SUPABASE_ANON_KEY", ""), url)
        check_postgrest("service key", os.environ.get("SUPABASE_SERVICE_KEY", ""), url)
    else:
        print("  SUPABASE_URL 없음 — 건너뜀")

    print("\n=== Postgres (직접 접속) ===")
    if dbu:
        check_postgres(dbu)
    else:
        print("  SUPABASE_DATABASE_URL 없음 — 건너뜀")


if __name__ == "__main__":
    main()
