# -*- coding: utf-8 -*-
"""RLS 권한 검증 — 배포 전 보안 게이트의 일부 (SPEC NFR-3, PLAN P-D2).

검증 항목:
  1. anon 키로 랭킹/메타 테이블 SELECT 가 된다        (웹이 동작해야 함)
  2. anon 키로 INSERT/UPDATE/DELETE 가 막힌다          (쓰기는 수집기만)
  3. anon 키로 ytr_quota_usage 를 읽을 수 없다         (운영 데이터 비노출)
  4. service 키로 쓰기가 된다                          (수집기가 동작해야 함)

시크릿은 출력하지 않는다. 사용법: python tools/verify_rls.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collector"))

READ_TABLES = [
    "ytr_categories",
    "ytr_regions",
    "ytr_channels",
    "ytr_channel_snapshots",
    "ytr_videos",
    "ytr_video_snapshots",
    "ytr_trend_scores",
]
HIDDEN_TABLES = ["ytr_quota_usage"]

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def record(check: str, ok: bool, detail: str = "") -> None:
    results.append((PASS if ok else FAIL, check, detail))
    mark = "✅" if ok else "❌"
    print(f"  {mark} {check}" + (f" — {detail}" if detail else ""))


def headers(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    import requests

    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    anon = os.environ.get("SUPABASE_ANON_KEY", "")
    svc = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not (url and anon and svc):
        sys.exit("SUPABASE_URL / SUPABASE_ANON_KEY / SUPABASE_SERVICE_KEY 가 .env 에 필요합니다")

    print("=== 1. anon SELECT 허용 (웹 읽기) ===")
    for t in READ_TABLES:
        r = requests.get(f"{url}/rest/v1/{t}?select=*&limit=1", headers=headers(anon), timeout=20)
        record(f"anon SELECT {t}", r.ok, f"HTTP {r.status_code}")

    print("\n=== 2. anon 쓰기 차단 ===")
    r = requests.post(
        f"{url}/rest/v1/ytr_categories",
        headers={**headers(anon), "Prefer": "return=minimal"},
        json=[{"id": "__rls_probe__", "name": "probe"}],
        timeout=20,
    )
    record("anon INSERT 차단", not r.ok, f"HTTP {r.status_code}")

    r = requests.patch(
        f"{url}/rest/v1/ytr_categories?id=eq.food",
        headers={**headers(anon), "Prefer": "return=minimal"},
        json={"name": "해킹됨"},
        timeout=20,
    )
    # RLS 로 대상 행이 보이지 않으면 200 + 0건 갱신이 될 수 있다 → 실제 변경 여부로 판정
    changed = False
    if r.ok:
        chk = requests.get(
            f"{url}/rest/v1/ytr_categories?id=eq.food&select=name",
            headers=headers(svc),
            timeout=20,
        )
        rows = chk.json() if chk.ok else []
        changed = bool(rows) and rows[0].get("name") == "해킹됨"
    record("anon UPDATE 무효", not changed, f"HTTP {r.status_code}, 값 변경={changed}")

    r = requests.delete(
        f"{url}/rest/v1/ytr_categories?id=eq.food", headers=headers(anon), timeout=20
    )
    deleted = False
    if r.ok:
        chk = requests.get(
            f"{url}/rest/v1/ytr_categories?id=eq.food&select=id", headers=headers(svc), timeout=20
        )
        deleted = chk.ok and len(chk.json()) == 0
    record("anon DELETE 무효", not deleted, f"HTTP {r.status_code}, 삭제됨={deleted}")

    print("\n=== 3. 운영 테이블 비노출 ===")
    for t in HIDDEN_TABLES:
        r = requests.get(f"{url}/rest/v1/{t}?select=*&limit=1", headers=headers(anon), timeout=20)
        record(f"anon SELECT {t} 차단", not r.ok, f"HTTP {r.status_code}")

    print("\n=== 4. service 키 쓰기 허용 ===")
    r = requests.post(
        f"{url}/rest/v1/ytr_regions?on_conflict=id",
        headers={**headers(svc), "Prefer": "resolution=merge-duplicates,return=minimal"},
        json=[{"id": "__probe__", "name": "probe"}],
        timeout=20,
    )
    record("service INSERT 허용", r.ok, f"HTTP {r.status_code}")
    if r.ok:
        d = requests.delete(
            f"{url}/rest/v1/ytr_regions?id=eq.__probe__", headers=headers(svc), timeout=20
        )
        record("service DELETE 허용 (probe 정리)", d.ok, f"HTTP {d.status_code}")

    n_fail = sum(1 for s, _, _ in results if s == FAIL)
    print(f"\n결과: {len(results) - n_fail} PASS / {n_fail} FAIL")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
