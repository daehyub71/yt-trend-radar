# -*- coding: utf-8 -*-
"""검증 탈락분을 대체 채널로 채운다 — 카테고리당 목표 15개 유지.

## bootstrap_seeds 와 다른 점

bootstrap 은 "찾아서 티어별로 뽑는다"까지만 한다. refill 은 **RSS 실검증을 통과한 채널만**
채택하므로, 뽑고 나서 버리는 낭비가 없다. 그리고 **결손이 채워지면 즉시 검색을 멈춘다** —
카테고리당 7회(700u)를 다 쓰지 않는다.

## 쿼터 주의

⚠️ 쿼터 원장은 **프로세스마다 0에서 시작한다**. 같은 날 여러 번 실행하면 일 상한을 넘길 수
   있다 (누적 기록은 P4 의 `ytr_quota_usage` 적재가 들어와야 가능하다).
   그때까지는 `--budget-units` 로 이번 실행분을 직접 제한한다.

실행:
  python -m jobs.refill_seeds --dry-run
  python -m jobs.refill_seeds --only vlog,travel --budget-units 1400
"""
import argparse
import sys
import time
from pathlib import Path

from core.config import DEFAULT_SEEDS, Settings, load_env_file, load_seeds, load_taxonomy
from core.quota import COSTS, QuotaExceeded, QuotaLedger
from engine.classifier import classify_channel
from jobs.bootstrap_seeds import (
    DEFAULT_QUOTAS,
    TIER_ORDER,
    entry_tier,
    looks_korean,
    render_seeds_yaml,
    tier_of,
)
from sources.rss_watcher import LiveRssWatcher
from sources.yt_client import get_youtube_client

VERDICTS = Path(__file__).resolve().parent.parent.parent / "docs" / "seeds_verdicts.json"

MAX_VERIFY_PER_CATEGORY = 70  # RSS 호출 상한 (공공 피드 예의)
RSS_DELAY = 0.3


def compute_deficit(kept: list[dict], quotas: dict[str, int]) -> dict[str, int]:
    """티어별 부족분. 초과 티어는 0 으로 본다 (다른 티어로 이월하지 않는다)."""
    have = {t: 0 for t in TIER_ORDER}
    for e in kept:
        t = entry_tier(e)
        if t:
            have[t] += 1
    return {t: max(0, quotas.get(t, 0) - have[t]) for t in TIER_ORDER}


def load_verdicts() -> dict:
    if not VERDICTS.exists():
        return {}
    import json

    return json.loads(VERDICTS.read_text(encoding="utf-8")).get("channels", {})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="이 카테고리만 (쉼표 구분)")
    ap.add_argument("--min-hit-rate", type=float, default=0.3)
    ap.add_argument("--min-subscribers", type=int, default=1_000)
    ap.add_argument("--niche-days", type=int, default=30)
    ap.add_argument("--budget-units", type=int, default=2_000, help="이번 실행의 쿼터 상한")
    ap.add_argument(
        "--fill-any-tier",
        action="store_true",
        help="티어 목표를 무시하고 '카테고리당 15개' 달성을 우선한다. "
        "대형(100만+) 후보가 고갈된 카테고리에서 쓴다 — 해당 규모의 한국 채널 수는 유한하다",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=str(DEFAULT_SEEDS))
    args = ap.parse_args()

    load_env_file()
    settings = Settings.from_env()
    tax = load_taxonomy()
    seeds = load_seeds()
    verdicts = load_verdicts()

    only = {c.strip() for c in args.only.split(",")} if args.only else None
    targets = [c for c in tax.categories if only is None or c.id in only]

    # 유지할 채널 = 검증 통과분 (미검증은 판단 근거가 없으므로 유지한다)
    kept: dict[str, list[dict]] = {}
    for c in tax.categories:
        rows = []
        for s in seeds.get(c.id, []):
            v = verdicts.get(s.channel_id)
            if v and "error" not in v and not v.get("ok"):
                continue  # 검증 탈락 → 교체 대상
            rows.append({"channel_id": s.channel_id, "handle": s.handle, "note": s.note})
        kept[c.id] = rows

    known: set[str] = {r["channel_id"] for rows in kept.values() for r in rows}
    known |= {s.channel_id for rows in seeds.values() for s in rows}  # 탈락분도 재채택 금지

    print(f"목표: 카테고리당 {sum(DEFAULT_QUOTAS.values())}개 · 구간 {DEFAULT_QUOTAS}")
    print(f"쿼터 상한(이번 실행): {args.budget_units}u\n")
    plan_units = 0
    for c in targets:
        d = compute_deficit(kept[c.id], DEFAULT_QUOTAS)
        need = sum(d.values())
        plan_units += min(len(c.discovery_queries_niche) + len(c.discovery_queries), 7) * 100
        print(f"  {c.id:9s} 유지 {len(kept[c.id]):2d} · 결손 {need:2d} {d}")
    print(f"\n최대 소요(전량 검색 시): {plan_units}u — 결손이 채워지면 조기 중단합니다")

    if args.dry_run:
        print("\ndry-run — 호출하지 않음")
        return 0

    quota = QuotaLedger(limit=args.budget_units)
    client = get_youtube_client(settings, quota=quota)
    watcher = LiveRssWatcher()

    target_total = sum(DEFAULT_QUOTAS.values())
    for c in targets:
        deficit = compute_deficit(kept[c.id], DEFAULT_QUOTAS)
        if args.fill_any_tier:
            # 티어 목표 대신 총량만 본다 (대형 후보 고갈 대응)
            short = max(0, target_total - len(kept[c.id]))
            deficit = {t: short for t in TIER_ORDER}
            remaining = short
        else:
            remaining = sum(deficit.values())
        if remaining == 0:
            print(f"\n[{c.id}] 결손 없음 — 건너뜀")
            continue

        print(f"\n[{c.id}] 결손 {remaining}개" + ("" if args.fill_any_tier else f" {deficit}"))
        n_verified = n_added = 0
        # niche(인기영상) 먼저 — 소형·신규 채널이 더 많이 잡힌다
        queries = [(q, "niche") for q in c.discovery_queries_niche]
        queries += [(q, "head") for q in c.discovery_queries]

        for query, kind in queries:
            if remaining == 0:
                print("  결손 해소 — 검색 중단")
                break
            if not quota.can_afford("search.list"):
                print(f"  ⚠️ 쿼터 상한 도달 ({quota.spent}/{quota.limit}u) — 중단")
                break
            try:
                refs = (
                    client.search_channels_via_videos(query, days=args.niche_days)
                    if kind == "niche"
                    else client.search_channels(query, max_results=25)
                )
            except QuotaExceeded:
                print("  ⚠️ 쿼터 초과 — 중단")
                break

            fresh = {r.channel_id: r.description for r in refs if r.channel_id not in known}
            if not fresh:
                print(f"  '{query}' → 새 후보 없음")
                continue

            stats = {f.channel.id: f.channel for f in client.fetch_channels(list(fresh))}
            pool = []
            for ch in stats.values():
                if (ch.subscriber_count or 0) < args.min_subscribers:
                    continue
                if not looks_korean(ch.title, fresh.get(ch.id, ""), ch.country):
                    continue
                t = tier_of(ch.subscriber_count)
                if t and deficit.get(t, 0) > 0:
                    pool.append((t, ch))
            pool.sort(key=lambda x: x[1].subscriber_count or 0, reverse=True)

            found_here = 0
            for t, ch in pool:
                if remaining == 0:
                    break
                if deficit[t] == 0:
                    continue
                if n_verified >= MAX_VERIFY_PER_CATEGORY:
                    break
                n_verified += 1
                try:
                    feed = watcher.fetch(ch.id)
                    verdict = classify_channel([e.title for e in feed.entries], tax)
                except Exception:  # noqa: BLE001
                    continue
                finally:
                    time.sleep(RSS_DELAY)
                if not verdict.accepts(c.id, min_hit_rate=args.min_hit_rate):
                    continue
                kept[c.id].append(
                    {
                        "channel_id": ch.id,
                        "handle": ch.handle or "",
                        "title": ch.title,
                        "subscriber_count": ch.subscriber_count,
                    }
                )
                known.add(ch.id)
                deficit[t] = max(0, deficit[t] - 1)
                remaining -= 1
                n_added += 1
                found_here += 1
                print(
                    f"    + [{t}] {ch.title[:28]:28s} {ch.subscriber_count:>9,} "
                    f"({verdict.matched}/{verdict.total})"
                )
            print(
                f"  '{query}' ({kind}) 후보 {len(pool)} → 채택 {found_here} "
                f"· 남은 결손 {remaining}"
            )

        print(f"  [{c.id}] 추가 {n_added}개 · RSS 검증 {n_verified}회 · 총 {len(kept[c.id])}개")

    ordered = {c.id: kept.get(c.id, []) for c in tax.categories}
    Path(args.out).write_text(
        render_seeds_yaml(ordered, {}, DEFAULT_QUOTAS), encoding="utf-8"
    )
    total = sum(len(v) for v in ordered.values())
    print(f"\n작성: {args.out} · 총 {total}개")
    print(f"쿼터 사용: {quota.summary()} (search {COSTS['search.list']}u/회)")
    for c in tax.categories:
        print(f"  {c.id:9s} {len(ordered[c.id]):2d}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
