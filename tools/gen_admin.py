# -*- coding: utf-8 -*-
"""운영 콘솔 (admin) 생성기 — docs/admin.html

성격: **상황판 + 러너블**. 버튼으로 작업을 실행하지 않는다 (PLAN P-D4 결정).
      웹에서 수집을 트리거하려면 인증 + service key 를 쓰는 서버 라우트가 필요하고,
      그것은 새 보안 표면이다. 이 페이지는 **읽기 전용 산출물**이므로 그 위험이 없다.

보여주는 것:
  1. 상태 타일 — 카테고리·시드·검증 통과율·DB 적재량·오늘 쿼터
  2. 자동 점검 — 시드 공백, 검증 노후, 통과율 저조, 수집 중단, purge 필요, 쿼터 임박
  3. 카테고리별 현황 — 시드 수, 검증 통과/탈락, 규모 분포
  4. 런북 — 카테고리 추가 등 유지보수 절차의 실행 명령 (복사 버튼)

DB 수치는 PostgREST 로 조회한다. 실패하거나 --offline 이면 해당 항목만 '조회 불가'로 표시하고
나머지는 그대로 렌더링한다 (운영 콘솔이 DB 장애로 함께 죽으면 쓸모가 없다).

사용법: python tools/gen_admin.py [--offline]
"""
import argparse
import html
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collector"))
sys.path.insert(0, str(ROOT / "tools"))

from _theme import page  # noqa: E402

OUT = ROOT / "docs" / "admin.html"
VERDICTS = ROOT / "docs" / "seeds_verdicts.json"

TIER_ORDER = ["micro", "small", "mid", "large"]
TIER_LABEL = {"micro": "마이크로", "small": "소형", "mid": "중형", "large": "대형"}

# 자동 점검 임계값 — 근거는 PLAN §6 리스크 표
VERIFY_STALE_DAYS = 7          # 검증 결과가 이보다 오래되면 노후
MIN_PASS_RATE = 0.6            # 카테고리 검증 통과율 하한
COLLECT_STALE_HOURS = 12       # PLAN: 12시간 무수집 시 알림
QUOTA_WARN_RATIO = 0.8         # 일 상한의 80% 넘으면 경고

# 콜드스타트 — 속도 지수는 스냅샷 2개 이상이 있어야 나오고, 의미 있는 순위는 축적이 필요하다.
COLDSTART_BEGAN = "2026-08-03"  # 첫 실수집일
COLDSTART_DAYS = 14

CSS = """
.checks { display:grid; gap:8px; }
.check { display:flex; gap:10px; align-items:flex-start; background:var(--surface);
  border:1px solid var(--border); border-radius:10px; padding:11px 14px; }
.check .icon { font-size:14px; line-height:1.4; flex:none; }
.check .body { flex:1; }
.check .what { font-size:13.5px; font-weight:600; }
.check .detail { font-size:12.5px; color:var(--ink-2); margin-top:2px; }
.check .fix { font-size:12px; margin-top:5px; }
.check.ok   { border-left:3px solid var(--good); }
.check.warn { border-left:3px solid var(--warn); }
.check.bad  { border-left:3px solid var(--bad); }
.check.na   { border-left:3px solid var(--rule); }
.check.ok .what   { color:var(--good-ink); }
.check.warn .what { color:var(--warn-ink); }
.check.bad .what  { color:var(--bad-ink); }
.check.na .what   { color:var(--muted); }

.tier { display:inline-flex; align-items:center; gap:5px; font-size:12px; font-weight:600;
  white-space:nowrap; margin-right:9px; font-variant-numeric:tabular-nums; }
.tier i { width:9px; height:9px; border-radius:2px; display:inline-block; }
.tier.micro { color:var(--t-micro-ink); } .tier.micro i { background:var(--t-micro); }
.tier.small { color:var(--t-small-ink); } .tier.small i { background:var(--t-small); }
.tier.mid   { color:var(--t-mid-ink); }   .tier.mid i   { background:var(--t-mid); }
.tier.large { color:var(--t-large-ink); } .tier.large i { background:var(--t-large); }

.rate { display:inline-flex; align-items:center; gap:6px; font-variant-numeric:tabular-nums;
  font-weight:600; font-size:12.5px; }
.rate.good { color:var(--good-ink); } .rate.poor { color:var(--bad-ink); }

.runbook { display:grid; gap:10px; }
.step { background:var(--surface); border:1px solid var(--border); border-radius:10px;
  padding:12px 14px; }
.step .title { font-size:13.5px; font-weight:650; }
.step .desc { font-size:12.5px; color:var(--ink-2); margin:3px 0 8px; }
.cmd { display:flex; gap:8px; align-items:center; margin-top:6px; }
.cmd code { flex:1; background:var(--surface-2); border:1px solid var(--border);
  border-radius:7px; padding:7px 10px; font-size:12px; overflow-x:auto; white-space:pre;
  color:var(--ink); }
button.copy { font:inherit; font-size:11.5px; font-weight:600; cursor:pointer; flex:none;
  background:var(--surface-2); color:var(--ink-2); border:1px solid var(--border);
  border-radius:7px; padding:6px 10px; }
button.copy[data-done="1"] { color:var(--good-ink); border-color:var(--good); }
.links { display:flex; flex-wrap:wrap; gap:10px; margin:6px 0 0; }
.links a { font-size:13px; font-weight:600; text-decoration:none;
  background:var(--surface); border:1px solid var(--border); border-radius:8px;
  padding:7px 12px; }
.links a:hover { border-color:var(--accent); }
.note { font-size:12.5px; color:var(--ink-2); }
"""

JS = """
document.querySelectorAll('button.copy').forEach(function (b) {
  b.addEventListener('click', function () {
    var code = b.parentElement.querySelector('code').textContent;
    navigator.clipboard.writeText(code).then(function () {
      var old = b.textContent;
      b.textContent = '복사됨';
      b.dataset.done = '1';
      setTimeout(function () { b.textContent = old; b.dataset.done = '0'; }, 1600);
    });
  });
});
"""


# ------------------------------------------------------------------ 데이터 수집


def db_stats(settings) -> dict | None:
    """PostgREST 로 테이블 행 수와 최신 수집 시각을 읽는다. 실패 시 None."""
    import requests

    from core.db import TABLES

    if not (settings.supabase_url and settings.supabase_service_key):
        return None
    h = {
        "apikey": settings.supabase_service_key,
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "Prefer": "count=exact",
        "Range": "0-0",
    }
    out: dict = {"counts": {}}
    try:
        for key in ("channels", "videos", "channel_snapshots", "video_snapshots", "trend_scores"):
            r = requests.get(
                f"{settings.supabase_url}/rest/v1/{TABLES[key]}?select=*", headers=h, timeout=20
            )
            r.raise_for_status()
            rng = r.headers.get("Content-Range", "")
            out["counts"][key] = int(rng.split("/")[-1]) if "/" in rng else None

        # 최신 스냅샷 시각 = 마지막 수집 시각
        r = requests.get(
            f"{settings.supabase_url}/rest/v1/{TABLES['video_snapshots']}"
            "?select=ts&order=ts.desc&limit=1",
            headers={k: v for k, v in h.items() if k not in ("Prefer", "Range")},
            timeout=20,
        )
        rows = r.json() if r.ok else []
        out["last_snapshot"] = rows[0]["ts"] if rows else None

        # 30일 초과 데이터 존재 여부 (purge 필요 판단)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.retention_days)).isoformat()
        r = requests.get(
            f"{settings.supabase_url}/rest/v1/{TABLES['video_snapshots']}?select=*&ts=lt.{cutoff}",
            headers=h,
            timeout=20,
        )
        rng = r.headers.get("Content-Range", "")
        out["stale_rows"] = int(rng.split("/")[-1]) if "/" in rng else 0

        # 오늘 쿼터 사용량
        today = datetime.now(timezone.utc).date().isoformat()
        r = requests.get(
            f"{settings.supabase_url}/rest/v1/{TABLES['quota_usage']}"
            f"?select=endpoint,calls,units&day=eq.{today}",
            headers={k: v for k, v in h.items() if k not in ("Prefer", "Range")},
            timeout=20,
        )
        out["quota_today"] = r.json() if r.ok else []

        # 최근 수집 회차 — 콜드스타트 동안 가장 자주 보게 되는 정보다.
        # 스냅샷 ts 를 분 단위로 묶으면 그게 곧 한 회차다.
        r = requests.get(
            f"{settings.supabase_url}/rest/v1/{TABLES['video_snapshots']}"
            "?select=ts&order=ts.desc&limit=4000",
            headers={k: v for k, v in h.items() if k not in ("Prefer", "Range")},
            timeout=25,
        )
        from collections import Counter

        rounds = Counter(x["ts"][:16] for x in (r.json() if r.ok else []))
        out["rounds"] = sorted(rounds.items(), reverse=True)[:8]

        # 보드 충전 상태 (카테고리 × 종류)
        r = requests.get(
            f"{settings.supabase_url}/rest/v1/{TABLES['trend_scores']}"
            "?select=category_id,scope,kind,format",
            headers={k: v for k, v in h.items() if k not in ("Prefer", "Range")},
            timeout=25,
        )
        out["boards"] = r.json() if r.ok else []
        return out
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}"
        return out


def load_verdicts() -> tuple[dict, dict]:
    if not VERDICTS.exists():
        return {}, {}
    data = json.loads(VERDICTS.read_text(encoding="utf-8"))
    return data.get("channels", {}), data


def parse_tier(note: str) -> str | None:
    for t in TIER_ORDER:
        if f"[{t}]" in (note or ""):
            return t
    return None


# ------------------------------------------------------------------ 렌더


# 점검 결과를 알림 경로로 흘려보내기 위한 수집기.
# 콘솔이 bad 를 띄워도 아무도 페이지를 안 열면 모른다 — 그래서 --strict 로 종료 코드를 준다.
FINDINGS: list[tuple[str, str]] = []


def check(state: str, what: str, detail: str = "", fix: str = "") -> str:
    FINDINGS.append((state, what))
    icon = {"ok": "✅", "warn": "⚠️", "bad": "❌", "na": "—"}[state]
    fix_html = f'<div class="fix"><code>{html.escape(fix)}</code></div>' if fix else ""
    detail_html = f'<div class="detail">{detail}</div>' if detail else ""
    return (
        f'<div class="check {state}"><span class="icon">{icon}</span><div class="body">'
        f'<div class="what">{html.escape(what)}</div>{detail_html}{fix_html}</div></div>'
    )


def step(title: str, desc: str, cmds: list[str]) -> str:
    body = "".join(
        f'<div class="cmd"><code>{html.escape(c)}</code>'
        f'<button class="copy" type="button">복사</button></div>'
        for c in cmds
    )
    return (
        f'<div class="step"><div class="title">{html.escape(title)}</div>'
        f'<div class="desc">{desc}</div>{body}</div>'
    )


def build(offline: bool) -> str:
    from core.config import Settings, load_env_file, load_seeds, load_taxonomy

    load_env_file()
    settings = Settings.from_env()
    tax = load_taxonomy()
    seeds = load_seeds()
    verdicts, meta = load_verdicts()

    stats = None if offline else db_stats(settings)
    now = datetime.now(timezone.utc)

    # --- 카테고리별 집계 -------------------------------------------------
    rows, total_seeds, total_pass, total_judged = [], 0, 0, 0
    empty_cats, poor_cats = [], []
    for c in tax.categories:
        entries = seeds.get(c.id, [])
        total_seeds += len(entries)
        n_ok = n_bad = 0
        dist = {t: 0 for t in TIER_ORDER}
        for s in entries:
            t = parse_tier(s.note)
            if t:
                dist[t] += 1
            v = verdicts.get(s.channel_id)
            if v and "error" not in v:
                if v.get("ok"):
                    n_ok += 1
                else:
                    n_bad += 1
        judged = n_ok + n_bad
        total_pass += n_ok
        total_judged += judged
        rate = n_ok / judged if judged else None
        if not entries:
            empty_cats.append(c.id)
        elif rate is not None and rate < MIN_PASS_RATE:
            poor_cats.append(f"{c.name} {rate:.0%}")

        tier_html = "".join(
            f'<span class="tier {t}"><i></i>{dist[t]}</span>' for t in TIER_ORDER if dist[t]
        )
        if rate is None:
            rate_html = '<span class="rate" style="color:var(--muted)">미검증</span>'
        else:
            cls = "good" if rate >= MIN_PASS_RATE else "poor"
            mark = "✅" if rate >= MIN_PASS_RATE else "❌"
            rate_html = f'<span class="rate {cls}">{mark} {n_ok}/{judged} · {rate:.0%}</span>'
        rows.append(
            f"<tr><td><b>{html.escape(c.name)}</b> "
            f'<code style="color:var(--muted)">{c.id}</code></td>'
            f'<td class="num">{len(entries)}</td>'
            f"<td>{rate_html}</td><td>{tier_html or '—'}</td></tr>"
        )

    pass_rate = total_pass / total_judged if total_judged else 0

    # --- 자동 점검 -------------------------------------------------------
    checks = []

    if empty_cats:
        checks.append(
            check(
                "bad",
                f"시드가 없는 카테고리 {len(empty_cats)}개",
                f"해당 카테고리 보드는 비어 있게 됩니다: <b>{', '.join(empty_cats)}</b>",
                f"python -m jobs.bootstrap_seeds --only {','.join(empty_cats)}",
            )
        )
    else:
        checks.append(check("ok", f"모든 카테고리에 시드 있음 ({total_seeds}개 채널)"))

    if not verdicts:
        checks.append(
            check("bad", "RSS 검증 기록 없음", "시드 품질을 확인하지 않은 상태입니다",
                  "python tools/verify_seeds.py")
        )
    else:
        gen = meta.get("generated_at")
        age_days = None
        if gen:
            try:
                age_days = (now - datetime.fromisoformat(gen)).days
            except ValueError:
                age_days = None
        if age_days is not None and age_days > VERIFY_STALE_DAYS:
            checks.append(
                check("warn", f"검증 기록이 {age_days}일 전", "채널은 주제를 바꾸기도 합니다",
                      "python tools/verify_seeds.py")
            )
        else:
            aged = f"{age_days}일 전" if age_days is not None else "시각 불명"
            checks.append(
                check("ok", f"RSS 검증 최신 ({aged})",
                      f"통과 {total_pass}/{total_judged} · {pass_rate:.0%}")
            )

    if poor_cats:
        checks.append(
            check(
                "warn",
                f"검증 통과율이 낮은 카테고리 {len(poor_cats)}개",
                f"{', '.join(poor_cats)} — 진짜 노이즈인지 <b>키워드 부족</b>인지 근거를 확인하세요",
                "python tools/gen_seeds_review.py   # 검토 페이지에서 ❌ 필터",
            )
        )

    if stats is None:
        checks.append(check("na", "DB 조회 건너뜀", "--offline 또는 자격증명 없음"))
    elif stats.get("error"):
        checks.append(check("warn", "DB 조회 실패", f"{stats['error']} — 네트워크·키를 확인하세요"))
    else:
        counts = stats["counts"]
        last = stats.get("last_snapshot")
        if not last:
            checks.append(
                check("warn", "수집 이력 없음", "스냅샷이 0건입니다 — 콜드스타트가 시작되지 않았습니다",
                      "python -m jobs.collect   # P4 에서 구현")
            )
        else:
            try:
                age_h = (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() / 3600
            except ValueError:
                age_h = None
            if age_h is not None and age_h > COLLECT_STALE_HOURS:
                checks.append(
                    check("bad", f"마지막 수집이 {age_h:.0f}시간 전",
                          f"{COLLECT_STALE_HOURS}시간 초과 — cron 이 멈췄을 수 있습니다")
                )
            else:
                checks.append(check("ok", f"수집 정상 (마지막 {age_h:.1f}시간 전)"))

        stale = stats.get("stale_rows") or 0
        if stale:
            checks.append(
                check("bad", f"{settings.retention_days}일 초과 데이터 {stale:,}행",
                      "YouTube ToS 보관 규정 위반 상태입니다", "python -m jobs.purge")
            )
        else:
            checks.append(check("ok", f"보관 정책 준수 ({settings.retention_days}일 초과 0행)"))

        if not counts.get("trend_scores"):
            checks.append(
                check("warn", "랭킹이 비어 있음", "지수 산출이 아직 실행되지 않았습니다",
                      "python -m jobs.compute   # P2 에서 구현")
            )

        units = sum(q.get("units", 0) for q in stats.get("quota_today") or [])
        limit = settings.yt_daily_quota_limit
        if units and units > limit * QUOTA_WARN_RATIO:
            checks.append(
                check("warn", f"오늘 쿼터 {units:,}/{limit:,}",
                      f"상한의 {units / limit:.0%} — 추가 발굴은 내일로 미루세요")
            )

    # --- 타일 ------------------------------------------------------------
    def tile(label, value, sub=""):
        s = f"<small> {sub}</small>" if sub else ""
        return (
            f'<div class="tile"><div class="label">{label}</div>'
            f'<div class="value">{value}{s}</div></div>'
        )

    counts = (stats or {}).get("counts", {})
    snap_total = (counts.get("video_snapshots") or 0) + (counts.get("channel_snapshots") or 0)

    # 콜드스타트 경과
    began = datetime.fromisoformat(COLDSTART_BEGAN).replace(tzinfo=timezone.utc)
    elapsed_days = max(0, (now - began).days)
    cs_pct = min(100, round(elapsed_days / COLDSTART_DAYS * 100))
    target = (began + timedelta(days=COLDSTART_DAYS)).date().isoformat()

    tiles = [
        tile("카테고리", len(tax.categories)),
        tile("시드 채널", total_seeds),
        tile("검증 통과", total_pass, f"/ {total_judged}" if total_judged else "· 미검증"),
        tile("스냅샷 행", f"{snap_total:,}" if stats and not stats.get("error") else "—"),
        tile("랭킹 행", f"{counts.get('trend_scores', 0):,}" if counts else "—"),
        tile("콜드스타트", f"{elapsed_days}", f"/ {COLDSTART_DAYS}일 · {cs_pct}%"),
    ]

    # 최근 수집 회차
    rounds = (stats or {}).get("rounds") or []
    if rounds:
        rows_r = "".join(
            f'<tr><td>{html.escape(ts.replace("T", " "))} UTC</td>'
            f'<td class="num">{n:,}</td></tr>'
            for ts, n in rounds
        )
        rounds_html = (
            '<div class="tablewrap"><table><thead><tr><th>수집 시각</th>'
            '<th style="text-align:right">영상 스냅샷</th></tr></thead>'
            f"<tbody>{rows_r}</tbody></table></div>"
        )
    else:
        rounds_html = '<p class="note">아직 수집 이력이 없습니다.</p>'

    # 보드 충전 상태
    board_rows = (stats or {}).get("boards") or []
    if board_rows:
        from collections import Counter

        cnt = Counter(
            (b["category_id"], b["scope"], b["kind"], b.get("format")) for b in board_rows
        )
        cols = [
            ("video", "trending", "long"), ("video", "trending", "short"),
            ("video", "rising", "long"), ("video", "rising", "short"),
            ("channel", "trending", None), ("channel", "rising", None),
        ]
        head = (
            "<tr><th>카테고리</th>"
            "<th>지금 뜨는<br>롱폼</th><th>지금 뜨는<br>Shorts</th>"
            "<th>새로 뜨는<br>롱폼</th><th>새로 뜨는<br>Shorts</th>"
            "<th>지금 뜨는<br>유튜버</th><th>새로 뜨는<br>유튜버</th></tr>"
        )
        body_rows = []
        for c in tax.categories:
            cells = []
            for scope, kind, fmt in cols:
                n = cnt.get((c.id, scope, kind, fmt), 0)
                style = "" if n else ' style="color:var(--muted)"'
                cells.append(f'<td class="num"{style}>{n or "—"}</td>')
            body_rows.append(
                f"<tr><td><b>{html.escape(c.name)}</b></td>{''.join(cells)}</tr>"
            )
        boards_html = (
            '<div class="tablewrap"><table><thead>' + head +
            f"</thead><tbody>{''.join(body_rows)}</tbody></table></div>"
        )
    else:
        boards_html = '<p class="note">아직 산출된 랭킹이 없습니다.</p>'

    # --- 런북 ------------------------------------------------------------
    runbook = [
        step(
            "1. 카테고리 추가",
            "<code>config/categories.yaml</code> 에 항목을 추가한다 — 이름·키워드·exclude·"
            "<code>discovery_queries</code>(채널검색)·<code>discovery_queries_niche</code>(인기영상). "
            "코드 수정은 필요 없다. 중복 키를 넣으면 테스트가 잡는다.",
            ["python -m pytest tests/test_config.py"],
        ),
        step(
            "2. 새 카테고리만 시드 발굴",
            "<b><code>--only</code> 를 반드시 쓴다</b> — 전체 재발굴은 카테고리당 700u 씩 "
            "쿼터를 다시 태운다. 기존 카테고리는 파일 값을 그대로 유지한다.",
            ["python -m jobs.bootstrap_seeds --only <category_id>"],
        ),
        step(
            "3. DB 에 카테고리 반영",
            "YAML 이 단일 진실이고 DB 테이블은 사본이다. 웹이 카테고리 이름을 읽으려면 동기화가 필요하다.",
            ["python -m jobs.sync_config"],
        ),
        step(
            "4. RSS 실검증 (쿼터 0)",
            "채널 최신 15개 영상 제목으로 카테고리 적합도를 판정한다. "
            "<b>탈락은 삭제 대상이 아니라 검토 대상</b>이다 — 키워드가 부족해 놓친 경우가 섞인다.",
            [
                "python tools/verify_seeds.py --only <category_id>",
                "python tools/verify_seeds.py --write   # 검토 후 탈락분 제거",
            ],
        ),
        step(
            "5. 검토·상황판 갱신",
            "생성 후 아티팩트로 게시하면 링크가 유지된다.",
            [
                "python tools/gen_seeds_review.py",
                "python tools/gen_admin.py",
                "python tools/gen_progress.py",
            ],
        ),
        step(
            "6. 보관 정책 집행",
            "YouTube ToS — 수집 데이터는 30일 내 갱신 또는 삭제. 수집 cron 이 매번 함께 실행한다.",
            ["python -m jobs.purge --dry-run", "python -m jobs.purge"],
        ),
    ]

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    body = f"""
<header>
  <div class="eyebrow">운영 콘솔</div>
  <h1>yt-trend-radar 유지보수</h1>
  <p class="sub">상황판 + 러너블 · 이 페이지는 읽기 전용 산출물이며 작업을 실행하지 않습니다 · 갱신 {stamp}</p>
</header>

<div class="tiles">{''.join(tiles)}</div>

<section>
  <h2>자동 점검</h2>
  <div class="checks">{''.join(checks)}</div>
</section>

<section>
  <h2>콜드스타트 진행</h2>
  <div class="barrow" style="margin-bottom:10px">
    <div class="bar" role="img" aria-label="콜드스타트 {cs_pct}%"><i style="width:{cs_pct}%"></i></div>
    <span class="num">{elapsed_days}/{COLDSTART_DAYS}일 · 공개 목표 {target}</span>
  </div>
  <p class="note" style="margin-bottom:12px">
    속도 지수는 같은 대상의 스냅샷이 2개 이상 있어야 계산됩니다. 축적 초기에 보드가 얇은 것은
    정상이며, 그동안 검색 색인은 차단해 둡니다(<code>SITE_PUBLIC</code> 미설정).
  </p>
  <h2>최근 수집 회차</h2>
  {rounds_html}
</section>

<section>
  <h2>보드 충전 상태</h2>
  {boards_html}
</section>

<section>
  <h2>카테고리 현황</h2>
  <div class="tablewrap"><table>
    <thead><tr><th>카테고리</th><th style="text-align:right">시드</th>
      <th>RSS 검증</th><th>규모 분포</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table></div>
  <p class="note" style="margin-top:8px">규모 분포: 색 + 숫자 병기 ·
    <span class="tier micro"><i></i>마이크로</span>
    <span class="tier small"><i></i>소형</span>
    <span class="tier mid"><i></i>중형</span>
    <span class="tier large"><i></i>대형</span></p>
</section>

<section>
  <h2>유지보수 런북</h2>
  <p class="note">프로젝트 루트에서 <code>collector/.venv</code> 를 활성화한 뒤 실행합니다.
    <code>PYTHONUTF8=1</code> 을 설정하세요 (한국어 Windows).</p>
  <div class="runbook">{''.join(runbook)}</div>
</section>

<section>
  <h2>관련 페이지</h2>
  <div class="links">
    <a href="./seeds_review.html">🔍 시드 검토</a>
    <a href="./progress.html">📡 진행 대시보드</a>
  </div>
  <p class="note" style="margin-top:8px">아티팩트로 게시된 링크는 별도입니다 — 위 링크는 로컬 파일 기준입니다.</p>
</section>

<footer>
  생성: <code>tools/gen_admin.py</code> · 토큰: <code>tools/_theme.py</code> (근거는 <code>docs/DESIGN.md</code>) ·
  점검 임계값: 검증 노후 {VERIFY_STALE_DAYS}일 / 통과율 하한 {MIN_PASS_RATE:.0%} /
  무수집 {COLLECT_STALE_HOURS}시간 / 쿼터 경고 {QUOTA_WARN_RATIO:.0%} ·
  점검 상태는 색 + 아이콘 + 문구를 함께 씁니다.
</footer>
"""
    return page("yt-trend-radar 운영 콘솔", CSS, body, JS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="DB 조회 건너뜀")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="심각(bad) 점검이 하나라도 있으면 비정상 종료한다. "
        "CI 에서 쓰면 워크플로 실패 → 알림으로 이어진다",
    )
    args = ap.parse_args()
    OUT.write_text(build(args.offline), encoding="utf-8")
    print(f"OK: {OUT}")

    bad = [w for s, w in FINDINGS if s == "bad"]
    warn = [w for s, w in FINDINGS if s == "warn"]
    print(f"점검: 심각 {len(bad)} · 주의 {len(warn)} · 정상 {sum(1 for s, _ in FINDINGS if s == 'ok')}")
    for w in bad:
        print(f"  ❌ {w}")
    for w in warn:
        print(f"  ⚠️ {w}")

    if args.strict and bad:
        print("\n--strict: 심각 점검이 있어 비정상 종료합니다")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
