# -*- coding: utf-8 -*-
"""config/seeds.yaml → docs/seeds_review.html 검토 페이지 생성기.

목적: 시드 90개를 눈으로 빠르게 검수한다 — 카테고리 오분류, 비한국어 채널, 규모 편중을
      찾아내고, 채널명을 눌러 유튜브에서 바로 확인한다.

색상: dataviz 스킬 검증 팔레트. 티어는 순서형(ordinal) 파랑 램프 4단,
      validate_palette.js --ordinal 로 라이트/다크 각각 ALL PASS 확인 (2026-07-30).
        light: #86b6ef #5598e7 #2a78d6 #184f95  (light-end 2.06:1)
        dark : #184f95 #256abf #3987e5 #86b6ef  (light-end 2.15:1)
      색만으로 정보를 전달하지 않는다 — 티어는 항상 라벨+구독자 수를 동반한다.
      재검토 플래그는 status/warning(#fab219, 라이트 1.79:1)이므로 아이콘+라벨 의무 동반.

사용법: python tools/gen_seeds_review.py
"""
import html
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collector"))

OUT = ROOT / "docs" / "seeds_review.html"
VERDICTS = ROOT / "docs" / "seeds_verdicts.json"

TIER_META = {
    "micro": ("마이크로", "1천~1만"),
    "small": ("소형", "1만~10만"),
    "mid": ("중형", "10만~100만"),
    "large": ("대형", "100만+"),
}
TIER_ORDER = ["micro", "small", "mid", "large"]
HANGUL = re.compile(r"[가-힣]")
NOTE_RE = re.compile(r"^(?P<title>.+?) · 구독자 (?P<subs>[\d,?]+)(?: \[(?P<tier>\w+)\])?$")


def parse_note(note: str) -> tuple[str, int | None, str | None]:
    m = NOTE_RE.match(note or "")
    if not m:
        return (note or "").strip(), None, None
    subs_raw = m.group("subs").replace(",", "")
    subs = int(subs_raw) if subs_raw.isdigit() else None
    return m.group("title").strip(), subs, m.group("tier")


def fmt_subs(n: int | None) -> str:
    if n is None:
        return "?"
    if n >= 10_000:
        return f"{n / 10_000:,.1f}만".replace(".0만", "만")
    return f"{n:,}"


CSS = """
:root {
  color-scheme: light;
  --page:#f9f9f7; --surface:#fcfcfb; --surface-2:#f3f2ee;
  --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --rule:#c3c2b7; --border:rgba(11,11,11,0.10);
  --accent:#2a78d6; --warn:#fab219; --warn-ink:#8a5a00;
  --good:#0ca30c; --good-ink:#006300; --bad:#d03b3b; --bad-ink:#d03b3b;
  --t-micro:#86b6ef; --t-small:#5598e7; --t-mid:#2a78d6; --t-large:#184f95;
  --t-micro-ink:#184f95; --t-small-ink:#184f95; --t-mid-ink:#1c5cab; --t-large-ink:#104281;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --page:#0d0d0d; --surface:#1a1a19; --surface-2:#232322;
    --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --rule:#383835; --border:rgba(255,255,255,0.10);
    --accent:#3987e5; --warn:#fab219; --warn-ink:#fab219;
    --good:#0ca30c; --good-ink:#0ca30c; --bad:#d03b3b; --bad-ink:#e66767;
    --t-micro:#184f95; --t-small:#256abf; --t-mid:#3987e5; --t-large:#86b6ef;
    --t-micro-ink:#86b6ef; --t-small-ink:#9ec5f4; --t-mid-ink:#b7d3f6; --t-large-ink:#cde2fb;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page:#0d0d0d; --surface:#1a1a19; --surface-2:#232322;
  --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --rule:#383835; --border:rgba(255,255,255,0.10);
  --accent:#3987e5; --warn:#fab219; --warn-ink:#fab219;
  --good:#0ca30c; --good-ink:#0ca30c; --bad:#d03b3b; --bad-ink:#e66767;
  --t-micro:#184f95; --t-small:#256abf; --t-mid:#3987e5; --t-large:#86b6ef;
  --t-micro-ink:#86b6ef; --t-small-ink:#9ec5f4; --t-mid-ink:#b7d3f6; --t-large-ink:#cde2fb;
}
:root[data-theme="light"] {
  color-scheme: light;
  --page:#f9f9f7; --surface:#fcfcfb; --surface-2:#f3f2ee;
  --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --rule:#c3c2b7; --border:rgba(11,11,11,0.10);
  --accent:#2a78d6; --warn:#fab219; --warn-ink:#8a5a00;
  --good:#0ca30c; --good-ink:#006300; --bad:#d03b3b; --bad-ink:#d03b3b;
  --t-micro:#86b6ef; --t-small:#5598e7; --t-mid:#2a78d6; --t-large:#184f95;
  --t-micro-ink:#184f95; --t-small-ink:#184f95; --t-mid-ink:#1c5cab; --t-large-ink:#104281;
}

body { background:var(--page); color:var(--ink); margin:0; line-height:1.5;
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif; }
.wrap { max-width:1040px; margin:0 auto; padding:36px 20px 64px; }
a { color:var(--accent); }

header .eyebrow { font-size:12px; letter-spacing:.08em; text-transform:uppercase;
  color:var(--muted); font-weight:600; }
header h1 { margin:4px 0 2px; font-size:25px; text-wrap:balance; }
header .sub { margin:0; color:var(--ink-2); font-size:13.5px; }

.tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:22px 0; }
.tile { background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:13px 15px; }
.tile .label { font-size:12px; color:var(--muted); font-weight:600; }
.tile .value { font-size:25px; font-weight:700; margin-top:2px; font-variant-numeric:tabular-nums; }
.tile .value small { font-size:13px; font-weight:500; color:var(--ink-2); }

/* 컨트롤 — 필터는 차트/표 위 한 줄 */
.controls { display:flex; flex-wrap:wrap; gap:8px; align-items:center;
  padding:12px 14px; background:var(--surface); border:1px solid var(--border);
  border-radius:10px; margin-bottom:18px; position:sticky; top:0; z-index:5; }
.controls .cgroup { display:flex; gap:6px; align-items:center; }
.controls .clabel { font-size:12px; color:var(--muted); font-weight:600; margin-right:2px; }
button.f { font:inherit; font-size:12.5px; font-weight:600; cursor:pointer;
  background:var(--surface-2); color:var(--ink-2); border:1px solid var(--border);
  border-radius:999px; padding:4px 12px; }
button.f[aria-pressed="true"] { background:var(--accent); color:#fff; border-color:transparent; }
button.f.warnbtn[aria-pressed="true"] { background:var(--warn); color:#0b0b0b; }
button.f:focus-visible, input:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
input[type="search"] { font:inherit; font-size:13px; padding:5px 10px; min-width:170px;
  background:var(--surface-2); color:var(--ink); border:1px solid var(--border); border-radius:8px; }

section.cat { margin-bottom:26px; }
.cathead { display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; margin-bottom:8px; }
.cathead h2 { font-size:16px; margin:0; }
.cathead .cid { font-size:12px; color:var(--muted); font-family:ui-monospace,monospace; }
.cathead .count { font-size:12.5px; color:var(--ink-2); font-variant-numeric:tabular-nums; margin-left:auto; }

/* 티어 분포 — 색 + 라벨 + 숫자 동반 (색 단독 전달 금지) */
.dist { display:flex; height:8px; border-radius:4px; overflow:hidden; background:var(--grid);
  margin-bottom:4px; gap:2px; }
.dist span { display:block; }
.distlegend { display:flex; flex-wrap:wrap; gap:12px; font-size:11.5px; color:var(--ink-2);
  margin-bottom:10px; font-variant-numeric:tabular-nums; }
.distlegend b { font-weight:600; }
.swatch { display:inline-block; width:9px; height:9px; border-radius:2px; margin-right:5px;
  vertical-align:baseline; }

.tablewrap { overflow-x:auto; border:1px solid var(--border); border-radius:10px; background:var(--surface); }
table { border-collapse:collapse; width:100%; font-size:13.5px; }
th { text-align:left; font-size:11.5px; text-transform:uppercase; letter-spacing:.04em;
  color:var(--muted); font-weight:600; padding:9px 12px; border-bottom:1px solid var(--rule);
  white-space:nowrap; }
td { padding:9px 12px; border-bottom:1px solid var(--grid); vertical-align:middle; }
tr:last-child td { border-bottom:none; }
tr.flagged { background:color-mix(in oklab, var(--warn) 8%, transparent); }
td.subs { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
td.name a { font-weight:600; text-decoration:none; }
td.name a:hover { text-decoration:underline; }
td.handle { color:var(--ink-2); font-size:12.5px; }
td.handle a { color:var(--ink-2); text-decoration:none; }
td.handle a:hover { text-decoration:underline; color:var(--accent); }
td.links { white-space:nowrap; }
td.links a { font-size:12px; text-decoration:none; margin-right:8px; }
td.links a:hover { text-decoration:underline; }
.cid-mono { font-family:ui-monospace,monospace; font-size:11.5px; color:var(--muted); }

.tier { display:inline-flex; align-items:center; gap:6px; font-size:12px; font-weight:600;
  white-space:nowrap; }
.tier i { width:9px; height:9px; border-radius:2px; display:inline-block; }
.tier.micro { color:var(--t-micro-ink); } .tier.micro i { background:var(--t-micro); }
.tier.small { color:var(--t-small-ink); } .tier.small i { background:var(--t-small); }
.tier.mid   { color:var(--t-mid-ink); }   .tier.mid i   { background:var(--t-mid); }
.tier.large { color:var(--t-large-ink); } .tier.large i { background:var(--t-large); }

.flag { display:inline-flex; align-items:center; gap:4px; font-size:11.5px; font-weight:600;
  color:var(--warn-ink); white-space:nowrap; }

/* RSS 실검증 판정 — 색 + 아이콘 + 수치를 함께 (색 단독 금지) */
.verdict { display:inline-flex; align-items:center; gap:5px; font-size:12px; font-weight:600;
  white-space:nowrap; font-variant-numeric:tabular-nums; }
.verdict.ok   { color:var(--good-ink); }
.verdict.bad  { color:var(--bad-ink); }
.verdict.none { color:var(--muted); font-weight:500; }
tr.rejected { background:color-mix(in oklab, var(--bad) 8%, transparent); }
.why { font-size:11.5px; color:var(--ink-2); }
.why em { font-style:normal; color:var(--muted); }
details.ev { margin:0; }
details.ev summary { font-size:11.5px; color:var(--accent); cursor:pointer; }
details.ev ul { margin:5px 0 0; padding-left:16px; }
details.ev li { font-size:11.5px; color:var(--ink-2); margin-bottom:2px; }
.norss { font-size:11.5px; color:var(--muted); }
.empty { padding:14px; color:var(--muted); font-size:13px; }
.hidden { display:none !important; }
footer { margin-top:32px; padding-top:12px; border-top:1px solid var(--grid);
  font-size:11.5px; color:var(--muted); }
footer code { font-family:ui-monospace,monospace; }
"""

JS = """
(function () {
  var tier = null, warnOnly = false, state = null, q = '';
  var rows = Array.prototype.slice.call(document.querySelectorAll('tr[data-tier]'));

  function apply() {
    rows.forEach(function (tr) {
      var okTier = !tier || tr.dataset.tier === tier;
      var okWarn = !warnOnly || tr.dataset.flag === '1';
      var okState = !state || tr.dataset.state === state;
      var okText = !q || tr.dataset.search.indexOf(q) !== -1;
      tr.classList.toggle('hidden', !(okTier && okWarn && okState && okText));
    });
    document.querySelectorAll('section.cat').forEach(function (s) {
      var shown = s.querySelectorAll('tr[data-tier]:not(.hidden)').length;
      s.querySelector('.count').textContent = shown + ' / ' + s.dataset.total + '개 표시';
      var empty = s.querySelector('.empty');
      if (empty) empty.classList.toggle('hidden', shown !== 0);
      var tbl = s.querySelector('table');
      if (tbl) tbl.classList.toggle('hidden', shown === 0);
    });
  }

  document.querySelectorAll('button.f[data-tier]').forEach(function (b) {
    b.addEventListener('click', function () {
      var v = b.dataset.tier;
      tier = (tier === v) ? null : v;
      document.querySelectorAll('button.f[data-tier]').forEach(function (o) {
        o.setAttribute('aria-pressed', String(o.dataset.tier === tier));
      });
      apply();
    });
  });
  document.querySelectorAll('button.f[data-state]').forEach(function (b) {
    b.addEventListener('click', function () {
      var v = b.dataset.state;
      state = (state === v) ? null : v;
      document.querySelectorAll('button.f[data-state]').forEach(function (o) {
        o.setAttribute('aria-pressed', String(o.dataset.state === state));
      });
      apply();
    });
  });
  var wb = document.querySelector('button.warnbtn');
  wb.addEventListener('click', function () {
    warnOnly = !warnOnly;
    wb.setAttribute('aria-pressed', String(warnOnly));
    apply();
  });
  document.querySelector('input[type=search]').addEventListener('input', function (e) {
    q = e.target.value.trim().toLowerCase();
    apply();
  });
  apply();
})();
"""


def load_verdicts() -> tuple[dict, float | None]:
    """RSS 실검증 결과 (tools/verify_seeds.py 산출). 없으면 빈 dict."""
    if not VERDICTS.exists():
        return {}, None
    import json

    data = json.loads(VERDICTS.read_text(encoding="utf-8"))
    return data.get("channels", {}), data.get("min_hit_rate")


def build() -> str:
    from core.config import load_seeds, load_taxonomy

    tax = load_taxonomy()
    seeds = load_seeds()
    names = {c.id: c.name for c in tax.categories}
    order = [c.id for c in tax.categories]
    verdicts, min_hit = load_verdicts()

    total = flagged = under = 0
    n_pass = n_rej = 0
    sections = []

    for cid in order:
        entries = seeds.get(cid, [])
        parsed = []
        for s in entries:
            title, subs, tier = parse_note(s.note)
            flag = not HANGUL.search(title)
            parsed.append(
                {
                    "id": s.channel_id,
                    "handle": s.handle,
                    "title": title,
                    "subs": subs,
                    "tier": tier or "?",
                    "flag": flag,
                }
            )
            total += 1
            flagged += 1 if flag else 0
            under += 1 if tier in ("micro", "small") else 0

        dist = {t: sum(1 for p in parsed if p["tier"] == t) for t in TIER_ORDER}
        n = max(len(parsed), 1)
        bars = "".join(
            f'<span style="flex:{dist[t]};background:var(--t-{t})"></span>'
            for t in TIER_ORDER
            if dist[t]
        )
        legend = " ".join(
            f'<span><i class="swatch" style="background:var(--t-{t})"></i>'
            f'{TIER_META[t][0]} <b>{dist[t]}</b></span>'
            for t in TIER_ORDER
        )

        body = []
        for p in sorted(parsed, key=lambda r: r["subs"] or 0, reverse=True):
            url = f"https://www.youtube.com/channel/{p['id']}"
            v = verdicts.get(p["id"], {})
            state = "none"
            if v and "error" not in v:
                state = "ok" if v.get("ok") else "bad"
                if state == "ok":
                    n_pass += 1
                else:
                    n_rej += 1
            got = names.get(v.get("verdict")) if v.get("verdict") else None
            if state == "ok":
                vcell = (
                    f'<span class="verdict ok">✅ {v["matched"]}/{v["total"]}'
                    f' · {v["hit_rate"]:.0%}</span>'
                )
                why = ""
            elif state == "bad":
                vcell = (
                    f'<span class="verdict bad">❌ {v["matched"]}/{v["total"]}'
                    f' · {v["hit_rate"]:.0%}</span>'
                )
                why = (
                    f'<div class="why">판정 <b>{html.escape(got)}</b></div>'
                    if got and got != names.get(cid)
                    else '<div class="why"><em>적중률 미달</em></div>'
                )
            else:
                vcell = '<span class="verdict none">— 미검증</span>'
                why = ""
            titles_ev = v.get("recent_titles") or []
            ev = (
                '<details class="ev"><summary>최근 영상</summary><ul>'
                + "".join(f"<li>{html.escape(t[:70])}</li>" for t in titles_ev)
                + "</ul></details>"
                if titles_ev
                else '<span class="norss">—</span>'
            )
            handle_cell = (
                f'<a href="https://www.youtube.com/{html.escape(p["handle"])}" '
                f'target="_blank" rel="noopener">{html.escape(p["handle"])}</a>'
                if p["handle"]
                else '<span class="cid-mono">—</span>'
            )
            tname = TIER_META.get(p["tier"], (p["tier"], ""))[0]
            search_blob = f"{p['title']} {p['handle']} {p['id']}".lower()
            row_cls = " class=\"rejected\"" if state == "bad" else (
                " class=\"flagged\"" if p["flag"] else ""
            )
            body.append(
                f'<tr data-tier="{p["tier"]}" data-flag="{"1" if p["flag"] else "0"}" '
                f'data-state="{state}" '
                f'data-search="{html.escape(search_blob, quote=True)}"{row_cls}>'
                f'<td><span class="tier {p["tier"]}"><i></i>{tname}</span></td>'
                f'<td class="subs">{fmt_subs(p["subs"])}</td>'
                f'<td class="name"><a href="{url}" target="_blank" rel="noopener">'
                f'{html.escape(p["title"])}</a>'
                f'{"<span class=\"flag\"> ⚠ 한글없음</span>" if p["flag"] else ""}</td>'
                f'<td class="handle">{handle_cell}</td>'
                f"<td>{vcell}{why}</td>"
                f"<td>{ev}</td>"
                f'<td class="links">'
                f'<a href="{url}/videos" target="_blank" rel="noopener">영상</a>'
                f'<a href="{url}/about" target="_blank" rel="noopener">정보</a></td>'
                f"</tr>"
            )

        sections.append(
            f'<section class="cat" data-total="{len(parsed)}">'
            f'<div class="cathead"><h2>{html.escape(names.get(cid, cid))}</h2>'
            f'<span class="cid">{cid}</span>'
            f'<span class="count">{len(parsed)} / {len(parsed)}개 표시</span></div>'
            f'<div class="dist" role="img" aria-label="티어 분포">{bars}</div>'
            f'<div class="distlegend">{legend}</div>'
            f'<div class="tablewrap"><table>'
            f"<thead><tr><th>규모</th><th style='text-align:right'>구독자</th>"
            f"<th>채널</th><th>핸들</th><th>RSS 검증</th><th>근거</th><th>열기</th></tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table>"
            f'<div class="empty hidden">조건에 맞는 채널이 없습니다.</div></div>'
            f"</section>"
        )

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    pct = under * 100 // max(total, 1)
    tier_buttons = "".join(
        f'<button class="f" data-tier="{t}" aria-pressed="false">'
        f"{TIER_META[t][0]} <span style='opacity:.7'>{TIER_META[t][1]}</span></button>"
        for t in TIER_ORDER
    )

    return f"""<title>yt-trend-radar 시드 채널 검토</title>
<style>{CSS}</style>
<div class="wrap">
<header>
  <div class="eyebrow">시드 채널 검토</div>
  <h1>추적 대상 {total}개 채널</h1>
  <p class="sub">config/seeds.yaml 기준 · 채널명을 누르면 유튜브에서 열립니다 · 갱신 {stamp}</p>
</header>

<div class="tiles">
  <div class="tile"><div class="label">전체 채널</div><div class="value">{total}</div></div>
  <div class="tile"><div class="label">카테고리</div><div class="value">{len(order)}</div></div>
  <div class="tile"><div class="label">10만 이하 (rising 풀)</div>
    <div class="value">{under}<small> · {pct}%</small></div></div>
  <div class="tile"><div class="label">RSS 검증 통과</div>
    <div class="value">{n_pass}<small> / {n_pass + n_rej}</small></div></div>
</div>

<div class="controls">
  <span class="clabel">규모</span>{tier_buttons}
  <span class="clabel" style="margin-left:8px">검증</span>
  <button class="f" data-state="ok" aria-pressed="false">✅ 통과</button>
  <button class="f" data-state="bad" aria-pressed="false">❌ 탈락</button>
  <button class="f warnbtn" aria-pressed="false">⚠ 한글없음</button>
  <input type="search" placeholder="채널·핸들·ID 검색" aria-label="채널 검색">
</div>

<p style="font-size:12.5px;color:var(--ink-2);margin:-6px 0 18px">
  <b>RSS 검증</b>: 채널 최신 영상 15개의 제목을 카테고리 키워드로 분류해, 목표 카테고리와
  일치하고 적중률이 {int((min_hit or 0.3) * 100)}% 이상일 때 통과입니다 (YouTube API 쿼터 0).
  <b>탈락은 삭제 대상이 아니라 검토 대상</b>입니다 — 키워드가 부족해 놓친 경우도 있으니
  "근거"의 실제 제목을 확인하세요.
</p>

{''.join(sections)}

<footer>
  생성: <code>tools/gen_seeds_review.py</code> ·
  색상: dataviz 검증 팔레트, 티어는 순서형 파랑 램프 4단(<code>--ordinal</code> 라이트/다크 ALL PASS) ·
  규모는 색 + 라벨 + 구독자 수를 함께 표기합니다(색 단독 전달 금지) ·
  "한글 없음"은 <b>비한국어 확정이 아니라 재검토 후보</b>입니다 —
  <code>UNDERkg</code>처럼 영문명 한국 채널이 있습니다.
</footer>
</div>
<script>{JS}</script>
"""


def main():
    OUT.write_text(build(), encoding="utf-8")
    print(f"OK: {OUT}")


if __name__ == "__main__":
    main()
