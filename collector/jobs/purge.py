# -*- coding: utf-8 -*-
"""30일 보관 정책 집행 (SPEC NFR-1 / YouTube API ToS).

수집 데이터는 30일 내에 갱신되거나 삭제되어야 한다. 이 잡은 삭제 쪽을 담당하며,
cron 에서 수집 직후 매번 돌린다 (배포 직전에 붙이는 장치가 아니다).

ytr_channels(채널 메타)는 대상이 아니다 — 계속 갱신되는 추적 대상이기 때문이다.
ytr_trend_scores 는 compute 주기마다 전량 교체되므로 별도 purge 가 필요 없다.

실행:  python -m jobs.purge          (RETENTION_DAYS 사용)
       python -m jobs.purge --days 7 (임시 override)
       python -m jobs.purge --dry-run
"""
import argparse
import sys
from datetime import timedelta

from core.config import Settings, load_env_file
from core.db import PURGE_TARGETS, get_db
from core.models import utcnow


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, help="보관 일수 override")
    ap.add_argument("--dry-run", action="store_true", help="삭제 없이 기준 시각만 출력")
    args = ap.parse_args()

    load_env_file()
    settings = Settings.from_env()
    days = args.days if args.days is not None else settings.retention_days
    cutoff = utcnow() - timedelta(days=days)

    print(f"보관 정책: {days}일 (DB_MODE={settings.db_mode})")
    print(f"삭제 기준: {cutoff.isoformat()} 이전")
    print(f"대상: {', '.join(f'{t}({c})' for t, c in PURGE_TARGETS)}")

    if args.dry_run:
        print("dry-run — 삭제하지 않음")
        return 0

    deleted = get_db(settings).purge_older_than(cutoff)
    total = sum(deleted.values())
    for table, n in deleted.items():
        print(f"  {table:20s} {n}건 삭제")
    print(f"합계 {total}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
