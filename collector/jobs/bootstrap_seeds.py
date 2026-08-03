# -*- coding: utf-8 -*-
"""시드 채널 발굴 → config/seeds.yaml 작성 (SPEC D4: 혼합 부트스트랩).

## 왜 층화 추출인가 (2026-07-30 설계 수정)

첫 구현은 발굴 결과를 **구독자 내림차순으로 정렬해 상위 N개**를 뽑았다. 결과적으로
구독자 100만~1,600만대 채널만 남았고, `RISING_SUBSCRIBER_MAX=100,000` 기준의
"신규 뜨는 유튜버" 보드가 텅 비게 된다. **추적 풀이 곧 발굴 한계**이므로, 시드는
규모 구간별 쿼터로 뽑아 소형 채널을 충분히 포함해야 한다.

발굴 경로도 두 가지를 섞는다:
  1. `type=channel` + head 질의       → 카테고리의 대표 대형 채널 (trending 보드용)
  2. `type=video, order=viewCount` + 롱테일 질의 (최근 N일)
     → "최근에 터진" 채널. 권위도가 아니라 최근 성과로 잡히므로 소형·신규가 섞인다

쿼터: search.list 100u/회. 기본 설정(카테고리 5개 × (head 3 + niche 4)) = 35회 = 3,500u

실행:
  python -m jobs.bootstrap_seeds --dry-run
  python -m jobs.bootstrap_seeds
  python -m jobs.bootstrap_seeds --quotas 5,6,3,1 --niche-days 60
"""
import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from core.config import DEFAULT_SEEDS, Settings, load_env_file, load_taxonomy
from core.quota import COSTS, QuotaExceeded, QuotaLedger
from sources.yt_client import get_youtube_client

# 구독자 규모 구간 [하한, 상한) — micro/small 합집합이 SPEC D7 의 rising 대상(10만 이하)이다
TIERS: dict[str, tuple[int, int]] = {
    "micro": (1_000, 10_000),
    "small": (10_000, 100_000),
    "mid": (100_000, 1_000_000),
    "large": (1_000_000, 10**12),
}

# 기본 쿼터: 15개 중 9개(60%)를 10만 이하로 — rising 발굴 풀을 확보한다
DEFAULT_QUOTAS: dict[str, int] = {"micro": 4, "small": 5, "mid": 4, "large": 2}

TIER_ORDER = ["micro", "small", "mid", "large"]


HANGUL = re.compile(r"[가-힣]")


def looks_korean(title: str = "", description: str = "", country: str | None = None) -> bool:
    """한국 대상 채널로 볼 수 있는가 (SPEC: 한국 중심 서비스).

    `relevanceLanguage=ko` 는 힌트일 뿐이라 영어권 채널이 대량 유입된다 — 실측상
    aicoding 카테고리는 15개 중 9개가 영어권이었다(freeCodeCamp, CBC News 등).
    AI·코딩 소재는 영어권 비중이 압도적이므로 이 필터 없이는 카테고리가 성립하지 않는다.

    판정: 국가코드가 KR 이거나, 채널명/소개에 한글이 있으면 통과.
          (국가코드는 비공개인 경우가 많고, 한국 채널이 영문명만 쓰는 경우도 있어 OR 로 본다)
    """
    if (country or "").upper() == "KR":
        return True
    return bool(HANGUL.search(title or "") or HANGUL.search(description or ""))


def tier_of(subscriber_count: int | None) -> str | None:
    if subscriber_count is None:
        return None
    for name, (lo, hi) in TIERS.items():
        if lo <= subscriber_count < hi:
            return name
    return None


def select_stratified(rows: list[dict], quotas: dict[str, int]) -> list[dict]:
    """구간별 쿼터로 채널을 고른다. 구간 내에서는 구독자 많은 순.

    어떤 구간에 후보가 부족하면 남은 자리를 다른 구간에서 채워 총량을 유지한다.
    """
    unique: dict[str, dict] = {}
    for r in rows:
        cid = r.get("channel_id")
        if cid and tier_of(r.get("subscriber_count")) is not None:
            unique.setdefault(cid, r)

    buckets: dict[str, list[dict]] = {t: [] for t in TIERS}
    for r in unique.values():
        buckets[tier_of(r["subscriber_count"])].append(r)
    for t in buckets:
        buckets[t].sort(key=lambda r: r["subscriber_count"], reverse=True)

    picked: list[dict] = []
    leftovers: list[dict] = []
    for t in TIER_ORDER:
        want = quotas.get(t, 0)
        picked.extend(buckets[t][:want])
        leftovers.extend(buckets[t][want:])

    # 부족분 보충 (작은 구간 우선 — 소형 채널 확보가 목적)
    shortfall = sum(quotas.values()) - len(picked)
    if shortfall > 0:
        leftovers.sort(key=lambda r: r["subscriber_count"])
        picked.extend(leftovers[:shortfall])

    picked.sort(key=lambda r: r["subscriber_count"], reverse=True)
    return picked


def _yaml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def entry_tier(entry: dict) -> str | None:
    """항목의 규모 구간. 병합된 기존 항목은 subscriber_count 가 없으므로 note 에서 읽는다."""
    subs = entry.get("subscriber_count")
    if isinstance(subs, int):
        return tier_of(subs)
    note = entry.get("note") or ""
    for name in TIER_ORDER:
        if f"[{name}]" in note:
            return name
    return None


def count_under_100k(found: dict[str, list[dict]]) -> int:
    small_tiers = {"micro", "small"}
    return sum(1 for v in found.values() for r in v if entry_tier(r) in small_tiers)


def render_seeds_yaml(
    found: dict[str, list[dict]], queries: dict[str, dict[str, list[str]]], quotas: dict[str, int]
) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = sum(len(v) for v in found.values())
    under = count_under_100k(found)
    lines = [
        "# 시드 채널 (SPEC D4: 혼합 부트스트랩)",
        "#",
        f"# ⚙️ jobs/bootstrap_seeds.py 생성 ({stamp}) — 채널 {total}개, 10만 이하 {under}개",
        "#    channel_id 는 모두 YouTube API 응답에서 온 실제 값이다 (추측 없음).",
        f"#    구간 쿼터: {quotas}  (micro<1만, small<10만, mid<100만, large≥100만)",
        "#    손으로 추가/삭제해도 된다. 재실행하면 덮어쓰므로 수동 편집분은 백업할 것.",
        "",
        "version: 1",
        "",
        "seeds:",
    ]
    for cid, entries in found.items():
        q = queries.get(cid, {})
        lines.append(f"  # {cid} — 채널검색: {', '.join(q.get('head', []))}")
        lines.append(f"  #{' ' * len(cid)}   인기영상: {', '.join(q.get('niche', []))}")
        if not entries:
            lines.append(f"  {cid}: []")
            lines.append("")
            continue
        lines.append(f"  {cid}:")
        for e in entries:
            # 기존 항목(병합분)은 원래 note 를 그대로 유지한다
            note = e.get("note")
            if not note:
                subs = e.get("subscriber_count")
                subs_txt = format(subs, ",") if isinstance(subs, int) else "?"
                note = f"{e.get('title', '')} · 구독자 {subs_txt} [{tier_of(subs) or '?'}]"
            lines.append(f"    - channel_id: {e['channel_id']}")
            lines.append(f"      handle: {_yaml_str(e.get('handle') or '')}")
            lines.append(f"      note: {_yaml_str(note)}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--quotas",
        default=",".join(str(DEFAULT_QUOTAS[t]) for t in TIER_ORDER),
        help=f"구간별 채택 수 (micro,small,mid,large) 기본 {DEFAULT_QUOTAS}",
    )
    ap.add_argument("--min-subscribers", type=int, default=1_000)
    ap.add_argument(
        "--allow-foreign",
        action="store_true",
        help="한국어 필터를 끈다 (기본은 한국 대상 채널만 — SPEC 한국 중심)",
    )
    ap.add_argument("--niche-days", type=int, default=30, help="인기영상 검색 기간(일)")
    ap.add_argument(
        "--only",
        help="이 카테고리만 발굴하고 나머지는 기존 seeds.yaml 값을 유지 (쉼표 구분). "
        "카테고리를 나중에 추가할 때 전체 쿼터를 다시 태우지 않기 위한 옵션",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=str(DEFAULT_SEEDS))
    args = ap.parse_args()

    try:
        vals = [int(v) for v in args.quotas.split(",")]
        quotas = dict(zip(TIER_ORDER, vals, strict=True))
    except (ValueError, TypeError):
        return print("--quotas 는 'micro,small,mid,large' 형식의 정수 4개") or 1

    load_env_file()
    settings = Settings.from_env()
    tax = load_taxonomy()

    only = {c.strip() for c in args.only.split(",")} if args.only else None
    if only:
        unknown = only - {c.id for c in tax.categories}
        if unknown:
            print(f"알 수 없는 카테고리: {sorted(unknown)}")
            return 1
    targets = [c for c in tax.categories if only is None or c.id in only]

    queries = {
        c.id: {"head": list(c.discovery_queries), "niche": list(c.discovery_queries_niche)}
        for c in tax.categories
    }
    n_searches = sum(
        len(queries[c.id]["head"]) + len(queries[c.id]["niche"]) for c in targets
    )
    est = n_searches * COSTS["search.list"]

    print(f"모드: YT_MODE={settings.yt_mode}")
    print(f"구간 쿼터: {quotas} (카테고리당 {sum(quotas.values())}개)")
    if only:
        print(f"대상 한정: {[c.id for c in targets]} (나머지는 기존 seeds.yaml 유지)")
    print(f"검색: {n_searches}회 → 예상 {est}u / 일 상한 {settings.yt_daily_quota_limit}u")
    for c in targets:
        q = queries[c.id]
        print(f"  {c.id:9s} head={q['head']}")
        print(f"  {' ':9s} niche={q['niche']}")

    if args.dry_run:
        print("\ndry-run — 호출하지 않음")
        return 0

    if est > settings.yt_daily_quota_limit:
        print("\n중단: 예상 쿼터가 일 상한을 넘습니다")
        return 1

    quota = QuotaLedger(limit=settings.yt_daily_quota_limit, search_budget_calls=n_searches)
    client = get_youtube_client(settings, quota=quota)

    # 병합 기반: --only 인 경우 나머지 카테고리는 기존 파일 값을 그대로 유지한다
    found: dict[str, list[dict]] = {}
    if only:
        from core.config import load_seeds

        try:
            existing = load_seeds(args.out)
        except FileNotFoundError:
            existing = {}
        for c in tax.categories:
            if c.id in only:
                continue
            found[c.id] = [
                {"channel_id": s.channel_id, "handle": s.handle, "note": s.note}
                for s in existing.get(c.id, [])
            ]
        kept = sum(len(v) for v in found.values())
        print(f"기존 유지: {kept}개")

    print("\n=== 발굴 ===")
    for cat in targets:
        refs: dict[str, str] = {}   # channel_id -> 검색 시점 소개글 (한국어 판정에 쓴다)
        n_head = n_niche = 0
        try:
            for q in cat.discovery_queries:
                for ref in client.search_channels(q, max_results=25):
                    if ref.channel_id not in refs:
                        refs[ref.channel_id] = ref.description
                        n_head += 1
            for q in cat.discovery_queries_niche:
                for ref in client.search_channels_via_videos(q, days=args.niche_days):
                    if ref.channel_id not in refs:
                        refs[ref.channel_id] = ref.description
                        n_niche += 1
        except QuotaExceeded as e:
            print(f"  ⚠️ 쿼터 중단: {e}")

        if not refs:
            print(f"  {cat.id:9s} 검색 결과 없음")
            found[cat.id] = []
            continue

        stats = {f.channel.id: f.channel for f in client.fetch_channels(list(refs))}
        rows, n_foreign = [], 0
        for ch in stats.values():
            if (ch.subscriber_count or 0) < args.min_subscribers:
                continue
            if not args.allow_foreign and not looks_korean(
                ch.title, refs.get(ch.id, ""), ch.country
            ):
                n_foreign += 1
                continue
            rows.append(
                {
                    "channel_id": ch.id,
                    "title": ch.title,
                    "handle": ch.handle or "",
                    "subscriber_count": ch.subscriber_count,
                }
            )
        found[cat.id] = select_stratified(rows, quotas)

        dist = {t: 0 for t in TIER_ORDER}
        for r in found[cat.id]:
            dist[tier_of(r["subscriber_count"])] += 1
        print(
            f"  {cat.id:9s} 후보 {len(refs)}개(채널검색 {n_head} + 인기영상 {n_niche}) "
            f"→ 비한국어 제외 {n_foreign} → 조건통과 {len(rows)} → 채택 {len(found[cat.id])} {dist}"
        )

    # 카테고리 정의 순서를 유지해 렌더링한다
    ordered = {c.id: found.get(c.id, []) for c in tax.categories}
    Path(args.out).write_text(render_seeds_yaml(ordered, queries, quotas), encoding="utf-8")
    found = ordered
    total = sum(len(v) for v in found.values())
    under = count_under_100k(found)
    print(f"\n작성: {args.out}")
    print(f"채널 {total}개 · 10만 이하 {under}개 ({under * 100 // max(total, 1)}%)")
    print(f"쿼터 사용: {quota.summary()}")
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
