# -*- coding: utf-8 -*-
"""db/migrations/*.sql 을 Supabase Postgres 에 순서대로 적용한다.

psql 없이 순수 파이썬(pg8000)으로 동작한다. 마이그레이션은 멱등(IF NOT EXISTS / OR REPLACE)
으로 작성되어 있으므로 재실행해도 안전하다.

TLS: Supabase 풀러는 자체 CA(Supabase Intermediate 2021 CA)로 서명된 인증서를 쓴다.
     공용 CA 스토어에 없으므로 다음 중 하나가 필요하다.
       --ca db/supabase-ca.crt   대시보드 → Project Settings → Database → SSL Configuration
                                 → Download certificate 로 받은 루트 CA (권장)
       --insecure                암호화는 하되 인증서 검증 생략 (로컬 1회성 적용 시에만)
     ⚠️ 수집기 런타임은 직접 접속을 쓰지 않는다 — PostgREST(HTTPS, 공용 CA 검증)만 사용하므로
        이 CA 이슈는 마이그레이션 도구에만 해당한다.

사용법:
  python tools/apply_migrations.py --ca db/supabase-ca.crt
  python tools/apply_migrations.py --insecure
  python tools/apply_migrations.py --dry-run
"""
import argparse
import ssl
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT / "db" / "migrations"


def split_statements(sql: str):
    """세미콜론으로 문장을 나눈다. $$ ... $$ 달러 인용 블록은 통째로 유지한다."""
    stmts, buf, i, n = [], [], 0, len(sql)
    dollar_tag = None
    while i < n:
        ch = sql[i]
        if dollar_tag:
            if sql.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
            buf.append(ch)
            i += 1
            continue
        if ch == "$":
            end = sql.find("$", i + 1)
            if end != -1 and all(c.isalnum() or c == "_" for c in sql[i + 1 : end]):
                dollar_tag = sql[i : end + 1]
                buf.append(dollar_tag)
                i = end + 1
                continue
        if ch == "-" and sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end == -1 else end
            continue
        if ch == "'":
            end = i + 1
            while end < n:
                if sql[end] == "'" and not sql.startswith("''", end):
                    break
                end += 2 if sql.startswith("''", end) else 1
            buf.append(sql[i : end + 1])
            i = end + 1
            continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def make_ssl_context(ca: str | None, insecure: bool):
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx, "암호화 O / 인증서 검증 X (--insecure)"
    if ca:
        ca_path = (ROOT / ca) if not Path(ca).is_absolute() else Path(ca)
        if not ca_path.exists():
            sys.exit(f"CA 파일 없음: {ca_path}")
        ctx = ssl.create_default_context(cafile=str(ca_path))
        return ctx, f"암호화 O / 검증 O (CA: {ca_path.name})"
    return ssl.create_default_context(), "암호화 O / 검증 O (시스템 CA)"


def connect(db_url: str, ssl_ctx, prefer_port: int | None):
    import pg8000.dbapi

    parts = urlsplit(db_url)
    kwargs = dict(
        user=unquote(parts.username or ""),
        password=unquote(parts.password or ""),
        host=parts.hostname or "",
        database=(parts.path or "/postgres").lstrip("/") or "postgres",
        ssl_context=ssl_ctx,
        timeout=30,
    )
    ports = [prefer_port] if prefer_port else [5432, parts.port or 6543]
    last = None
    for port in ports:
        try:
            conn = pg8000.dbapi.connect(port=port, **kwargs)
            print(f"  접속: port {port} ({'session' if port == 5432 else 'transaction'} pooler)")
            return conn
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  port {port} 실패: {type(e).__name__}: {str(e)[:150]}")
    raise SystemExit(f"접속 실패: {last}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ca", help="루트 CA 인증서 경로 (예: db/supabase-ca.crt)")
    ap.add_argument("--insecure", action="store_true", help="인증서 검증 생략 (로컬 1회성)")
    ap.add_argument("--dry-run", action="store_true", help="문장만 파싱해 보여주고 종료")
    ap.add_argument("--port", type=int, help="접속 포트 강제 (5432 세션 / 6543 트랜잭션)")
    args = ap.parse_args()

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        sys.exit(f"마이그레이션 없음: {MIGRATIONS_DIR}")

    plan = [(f, split_statements(f.read_text(encoding="utf-8"))) for f in files]
    print("=== 마이그레이션 ===")
    print(f"  파일 {len(plan)}개, 문장 {sum(len(s) for _, s in plan)}개")

    if args.dry_run:
        for f, stmts in plan:
            print(f"  {f.name}: {len(stmts)} statements")
            for s in stmts:
                print(f"    - {s.splitlines()[0][:90]}")
        return

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    import os

    db_url = os.environ.get("SUPABASE_DATABASE_URL", "")
    if not db_url:
        sys.exit("SUPABASE_DATABASE_URL 이 .env 에 없습니다")

    ssl_ctx, mode = make_ssl_context(args.ca, args.insecure)
    print(f"  TLS: {mode}")
    conn = connect(db_url, ssl_ctx, args.port)
    cur = conn.cursor()
    total = 0
    try:
        for f, stmts in plan:
            print(f"\n  ▶ {f.name} ({len(stmts)} statements)")
            for idx, stmt in enumerate(stmts, 1):
                head = stmt.splitlines()[0][:80]
                try:
                    cur.execute(stmt)
                    total += 1
                    print(f"    [{idx:2d}] OK   {head}")
                except Exception as e:  # noqa: BLE001
                    conn.rollback()
                    print(f"    [{idx:2d}] FAIL {head}")
                    print(f"         {type(e).__name__}: {str(e)[:300]}")
                    raise SystemExit(1)
        conn.commit()
    finally:
        conn.close()
    print(f"\n완료: {total} statements 적용")


if __name__ == "__main__":
    main()
