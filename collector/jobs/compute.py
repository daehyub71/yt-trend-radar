# -*- coding: utf-8 -*-
"""스냅샷 시계열 → 랭킹 산출 → ytr_trend_scores 원자적 교체 (SPEC FR-7).

수집(collect) 직후에 돌린다. 웹은 이 잡의 결과만 읽으므로,
이 잡이 실패해도 **직전 랭킹이 그대로 서빙된다** (교체는 RPC 안에서 원자적으로 일어난다).

콜드스타트 주의: 스냅샷이 2개 미만인 대상은 속도를 계산할 수 없어 보드에서 빠진다.
따라서 수집 시작 직후 며칠은 보드가 얇다 — 정상이며, 상황판이 그 사실을 보여준다.

실행:
  python -m jobs.compute
  python -m jobs.compute --dry-run          # 산출만 하고 게시하지 않음
  python -m jobs.compute --limit 30 --top 5 # 보드당 30개, 상위 5개 미리보기 출력
"""
import argparse
import sys
from datetime import timedelta

from core.config import Settings, load_env_file, load_taxonomy
from core.db import get_db
from core.models import utcnow
from engine.trend_engine import BOARDS, DEFAULT_LIMIT, build_boards

BOARD_LABEL = {
    ("video", "trending"): "지금 뜨는 영상",
    ("video", "rising"): "신규 뜨는 영상",
    ("channel", "trending"): "지금 뜨는 유튜버",
    ("channel", "rising"): "신규 뜨는 유튜버",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="보드당 최대 항목 수")
    ap.add_argument("--top", type=int, default=3, help="미리보기로 출력할 상위 개수")
    ap.add_argument("--dry-run", action="store_true", help="게시하지 않음")
    args = ap.parse_args()

    load_env_file()
    settings = Settings.from_env()
    tax = load_taxonomy()
    db = get_db(settings)
    now = utcnow()

    # 산출에 필요한 만큼만 읽는다. 가장 긴 구간(채널 7일) + 영상 나이 상한(7일)을 덮도록
    # 여유를 두되, 보관 정책(30일) 안에서만 읽는다.
    lookback = min(settings.retention_days, 30)
    cutoff = now - timedelta(days=lookback)

    p = settings.trend
    print(f"모드: DB_MODE={settings.db_mode} · 기준 시각 {now.isoformat()}")
    print(f"조회 구간: 최근 {lookback}일")
    print(
        f"지수 파라미터: α(지금 뜨는)={p.alpha_trending} · α(신규 뜨는)={p.alpha_rising} · "
        f"floor={p.subscriber_floor:,} · rising 구독자 상한={p.rising_subscriber_max:,}"
    )

    channels = db.fetch_all_channels()
    videos = db.fetch_videos_published_since(cutoff)
    vsnaps = db.fetch_video_snapshots_since(cutoff)
    csnaps = db.fetch_channel_snapshots_since(cutoff)
    print(
        f"  채널 {len(channels)} · 영상 {len(videos)} · "
        f"영상 스냅샷 {sum(len(v) for v in vsnaps.values())} "
        f"· 채널 스냅샷 {sum(len(v) for v in csnaps.values())}"
    )

    if not vsnaps and not csnaps:
        print("\n⚠️ 스냅샷이 없습니다 — 수집(jobs/collect)이 아직 돌지 않았습니다.")
        print("   기존 랭킹을 지우지 않고 종료합니다 (빈 보드로 교체하면 서비스가 빕니다).")
        return 1

    categories = [c.id for c in tax.categories]
    scores = build_boards(
        categories=categories,
        videos=videos,
        video_snapshots=vsnaps,
        channels=channels,
        channel_snapshots=csnaps,
        now=now,
        limit=args.limit,
        params=settings.trend,   # .env 설정이 실제로 반영된다
    )

    print(f"\n=== 보드 ({len(scores)}행) ===")
    print(f"  {'카테고리':9s} " + " · ".join(
        f"{BOARD_LABEL[(scope, kind)]}" + ("(롱/숏)" if scope == "video" else "")
        for scope, kind, _ in BOARDS
    ))
    for cat in categories:
        parts = []
        for scope, kind, _cfg in BOARDS:
            rows = [s for s in scores
                    if s.category_id == cat and s.scope == scope and s.kind == kind]
            if scope == "video":
                n_long = sum(1 for s in rows if s.format == "long")
                n_short = sum(1 for s in rows if s.format == "short")
                parts.append(f"{n_long:>3d}/{n_short:<3d}")
            else:
                parts.append(f"{len(rows):>3d}   ")
        print(f"  {cat:9s} " + " · ".join(parts))

    if args.top:
        for cat in categories:
            for scope, kind, _cfg in BOARDS:
                top = [
                    s for s in scores
                    if s.category_id == cat and s.scope == scope and s.kind == kind
                ][: args.top]
                if not top:
                    continue
                print(f"\n  [{cat}] {BOARD_LABEL[(scope, kind)]}")
                for s in top:
                    print(
                        f"    {s.rank}. {(s.title or '')[:34]:34s} "
                        f"score={s.score:>10.2f} Δ={s.delta_views:>9,} / {s.window_hours}h"
                    )

    if args.dry_run:
        print("\ndry-run — 게시하지 않음")
        return 0

    if not scores:
        print("\n⚠️ 산출된 랭킹이 0행 — 게시하지 않습니다 (기존 보드 유지).")
        return 1

    n = db.publish_trend_scores([s.to_row() for s in scores])
    print(f"\n게시 완료: {n}행 (원자적 교체)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
