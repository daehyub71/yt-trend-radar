# -*- coding: utf-8 -*-
"""시드 채널을 RSS 로 실검증한다 — **YouTube Data API 쿼터 0**.

왜: 시드 발굴이 '영상 1건이 질의에 맞으면 채널 채택' 이라 오분류가 섞였다.
    실제 사고 — 시사 채널(어쩌다시사)이 편의점 관련 영상 하나로 food 에 들어왔다.
    채널은 최근 영상 제목 전체로 판정해야 한다.

방식: 채널 RSS(최신 15개) → engine.classifier.classify_channel → 목표 카테고리와 비교.
      결과를 docs/seeds_verdicts.json 에 남기고, 검토 페이지가 이를 읽어 근거를 보여준다.

공공 API 예의: 요청 사이 간격을 둔다 (기본 0.35초). 90개면 약 1분.

사용법:
  python tools/verify_seeds.py                    # 검증 + 리포트 + JSON 기록
  python tools/verify_seeds.py --min-hit-rate 0.4
  python tools/verify_seeds.py --write            # 탈락 채널을 seeds.yaml 에서 제거
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collector"))

OUT_JSON = ROOT / "docs" / "seeds_verdicts.json"
SEEDS = ROOT / "config" / "seeds.yaml"


def main() -> int:
    from core.config import load_seeds, load_taxonomy
    from engine.classifier import classify_channel
    from sources.rss_watcher import LiveRssWatcher

    ap = argparse.ArgumentParser()
    ap.add_argument("--min-hit-rate", type=float, default=0.3, help="채택 최소 적중률")
    ap.add_argument("--delay", type=float, default=0.35, help="요청 간 간격(초)")
    ap.add_argument("--write", action="store_true", help="탈락 채널을 seeds.yaml 에서 제거")
    ap.add_argument("--only", help="이 카테고리만 검증 (쉼표 구분)")
    args = ap.parse_args()

    tax = load_taxonomy()
    seeds = load_seeds()
    only = {c.strip() for c in args.only.split(",")} if args.only else None
    watcher = LiveRssWatcher()

    targets = [(cid, s) for cid, entries in seeds.items() for s in entries
               if only is None or cid in only]
    print(f"검증 대상: {len(targets)}개 채널 (RSS, 쿼터 0)")
    print(f"기준: 목표 카테고리 일치 + 적중률 >= {args.min_hit_rate:.0%}\n")

    verdicts: dict[str, dict] = {}
    fails: dict[str, list[str]] = {}
    n_pass = n_fail = n_err = 0

    for i, (cid, seed) in enumerate(targets, 1):
        title = (seed.note or "").split(" · ")[0]
        try:
            feed = watcher.fetch(seed.channel_id)
            titles = [e.title for e in feed.entries]
            v = classify_channel(titles, tax)
            ok = v.accepts(cid, min_hit_rate=args.min_hit_rate)
            verdicts[seed.channel_id] = {
                "target": cid,
                "verdict": v.category_id,
                "matched": v.matched,
                "total": v.total,
                "hit_rate": round(v.hit_rate, 3),
                "dominance": round(v.dominance, 3),
                "distribution": v.distribution,
                "samples": v.samples,
                "recent_titles": titles[:5],
                "ok": ok,
            }
            if ok:
                n_pass += 1
                mark = "✅"
            else:
                n_fail += 1
                fails.setdefault(cid, []).append(seed.channel_id)
                mark = "❌"
            names = {c.id: c.name for c in tax.categories}
            got = names.get(v.category_id, "미분류") if v.category_id else "미분류"
            print(
                f"  [{i:3d}/{len(targets)}] {mark} {cid:9s} {title[:26]:26s} "
                f"→ {got:12s} {v.matched}/{v.total} ({v.hit_rate:.0%})"
            )
        except Exception as e:  # noqa: BLE001
            n_err += 1
            verdicts[seed.channel_id] = {"target": cid, "error": f"{type(e).__name__}"}
            print(f"  [{i:3d}/{len(targets)}] ⚠️ {cid:9s} {title[:26]:26s} → {type(e).__name__}")
        if args.delay:
            time.sleep(args.delay)

    OUT_JSON.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "min_hit_rate": args.min_hit_rate,
                "channels": verdicts,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    print(f"\n통과 {n_pass} · 탈락 {n_fail} · 오류 {n_err}")
    print(f"기록: {OUT_JSON.relative_to(ROOT)}")

    if fails:
        print("\n=== 카테고리별 탈락 ===")
        for cid, ids in fails.items():
            print(f"  {cid:9s} {len(ids)}개")

    if args.write and fails:
        removed = _rewrite_seeds(seeds, fails, tax)
        print(f"\nseeds.yaml 갱신: {removed}개 제거")
    elif fails:
        print("\n(제거하려면 --write. 먼저 검토 페이지에서 근거를 확인하세요)")

    return 0


def _rewrite_seeds(seeds, fails: dict[str, list[str]], tax) -> int:
    """탈락 채널을 제거하고 seeds.yaml 을 다시 쓴다."""
    sys.path.insert(0, str(ROOT / "collector"))
    from jobs.bootstrap_seeds import DEFAULT_QUOTAS, render_seeds_yaml

    drop = {cid: set(ids) for cid, ids in fails.items()}
    kept: dict[str, list[dict]] = {}
    removed = 0
    for c in tax.categories:
        rows = []
        for s in seeds.get(c.id, []):
            if s.channel_id in drop.get(c.id, ()):
                removed += 1
                continue
            rows.append({"channel_id": s.channel_id, "handle": s.handle, "note": s.note})
        kept[c.id] = rows
    SEEDS.write_text(render_seeds_yaml(kept, {}, DEFAULT_QUOTAS), encoding="utf-8")
    return removed


if __name__ == "__main__":
    sys.exit(main())
