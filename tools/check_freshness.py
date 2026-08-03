# -*- coding: utf-8 -*-
"""수집 신선도 점검 — 오래됐으면 **비정상 종료**한다 (CI 실패 = 알림).

왜 별도 스크립트/워크플로인가: 이 점검을 수집 워크플로 안에 두면, **cron 자체가 멈췄을 때
아무도 알려주지 않는다**. 수집과 독립적으로 도는 감시자가 필요하다.

기준: 마지막 영상 스냅샷이 --max-age-hours(기본 12) 보다 오래되면 실패.
      PLAN §6 의 "12시간 무수집 시 알림"과 같은 기준이다.

실행:
  python tools/check_freshness.py
  python tools/check_freshness.py --max-age-hours 24
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collector"))


def main() -> int:
    from core.config import Settings, load_env_file
    from core.db import TABLES, get_db

    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-hours", type=float, default=12.0)
    ap.add_argument("--allow-empty", action="store_true",
                    help="스냅샷이 아예 없어도 통과 (콜드스타트 시작 전)")
    args = ap.parse_args()

    load_env_file()
    settings = Settings.from_env()
    db = get_db(settings)
    now = datetime.now(timezone.utc)

    rows = db._request(  # noqa: SLF001 - 단일 목적 점검 스크립트
        "GET",
        f"/rest/v1/{TABLES['video_snapshots']}?select=ts&order=ts.desc&limit=1",
    ).json()

    if not rows:
        print("스냅샷 0건 — 수집이 아직 시작되지 않았습니다")
        return 0 if args.allow_empty else 1

    last = datetime.fromisoformat(rows[0]["ts"].replace("Z", "+00:00"))
    age_h = (now - last).total_seconds() / 3600
    print(f"마지막 수집: {last.isoformat()} ({age_h:.1f}시간 전)")

    # 오늘 쿼터도 함께 보고한다 (누적 추적의 근거)
    try:
        spent = db.quota_spent_today(now.date().isoformat())
        print(f"오늘 쿼터: {spent}/{settings.yt_daily_quota_limit}u")
    except Exception as e:  # noqa: BLE001
        print(f"쿼터 조회 실패: {type(e).__name__}")

    if age_h > args.max_age_hours:
        print(f"❌ {args.max_age_hours}시간 초과 — cron 이 멈췄을 수 있습니다")
        return 1
    print("✅ 정상")
    return 0


if __name__ == "__main__":
    sys.exit(main())
