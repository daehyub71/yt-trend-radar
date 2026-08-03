# -*- coding: utf-8 -*-
"""내부 도구 페이지의 공통 디자인 토큰과 기본 레이아웃 CSS.

⚠️ **여기가 코드 상의 단일 정의점이다.** 값의 근거와 검증 기록은 `docs/DESIGN.md` 가 소유한다
   (§1 토큰, §2 티어 순서형 램프, §2b 판정 상태색 텍스트 대비). 값을 바꾸려면
   DESIGN.md 를 먼저 고치고 `validate_palette.js` 재실행 결과를 기록한 뒤 여기 반영한다.

토큰을 세 곳(진행 대시보드·시드 검토·운영 콘솔)에 복붙하면 곧 어긋난다 — 그래서 모듈로 뽑았다.
"""

# 라이트/다크 양쪽 + 사용자 토글(data-theme) 3개 스코프에 같은 토큰 집합을 선언한다.
# 토글이 OS 설정을 양방향으로 이겨야 하므로 media query 는 :where() 로 특이도를 낮춘다.
_LIGHT = """
  color-scheme: light;
  --page:#f9f9f7; --surface:#fcfcfb; --surface-2:#f3f2ee;
  --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --rule:#c3c2b7; --border:rgba(11,11,11,0.10);
  --accent:#2a78d6;
  --good:#0ca30c; --good-ink:#006300;
  --bad:#d03b3b;  --bad-ink:#d03b3b;
  --warn:#fab219; --warn-ink:#8a5a00;
  --t-micro:#86b6ef; --t-small:#5598e7; --t-mid:#2a78d6; --t-large:#184f95;
  --t-micro-ink:#184f95; --t-small-ink:#184f95; --t-mid-ink:#1c5cab; --t-large-ink:#104281;
"""

_DARK = """
  color-scheme: dark;
  --page:#0d0d0d; --surface:#1a1a19; --surface-2:#232322;
  --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --rule:#383835; --border:rgba(255,255,255,0.10);
  --accent:#3987e5;
  --good:#0ca30c; --good-ink:#0ca30c;
  --bad:#d03b3b;  --bad-ink:#e66767;
  --warn:#fab219; --warn-ink:#fab219;
  --t-micro:#184f95; --t-small:#256abf; --t-mid:#3987e5; --t-large:#86b6ef;
  --t-micro-ink:#86b6ef; --t-small-ink:#9ec5f4; --t-mid-ink:#b7d3f6; --t-large-ink:#cde2fb;
"""

TOKENS = f""":root {{{_LIGHT}}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{{_DARK}}}
}}
:root[data-theme="dark"] {{{_DARK}}}
:root[data-theme="light"] {{{_LIGHT}}}
"""

BASE = """
body { background:var(--page); color:var(--ink); margin:0; line-height:1.5;
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif; }
a { color:var(--accent); }
.wrap { max-width:1040px; margin:0 auto; padding:36px 20px 64px; }

header .eyebrow { font-size:12px; letter-spacing:.08em; text-transform:uppercase;
  color:var(--muted); font-weight:600; }
header h1 { margin:4px 0 2px; font-size:25px; text-wrap:balance; }
header .sub { margin:0; color:var(--ink-2); font-size:13.5px; }

.tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:22px 0; }
.tile { background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:13px 15px; }
.tile .label { font-size:12px; color:var(--muted); font-weight:600; }
.tile .value { font-size:25px; font-weight:700; margin-top:2px; font-variant-numeric:tabular-nums; }
.tile .value small { font-size:13px; font-weight:500; color:var(--ink-2); }

.bar { background:var(--grid); border-radius:4px; height:8px; overflow:hidden; display:flex; gap:2px; }
.bar > i, .bar > span { display:block; height:100%; }
.bar > i { background:var(--accent); border-radius:4px; min-width:2px; }
.bar > i.zero { min-width:0; }
.barrow { display:flex; align-items:center; gap:10px; }
.barrow .bar { flex:1; }
.barrow .num { font-variant-numeric:tabular-nums; font-size:12.5px; color:var(--ink-2); white-space:nowrap; }

section h2 { font-size:16px; margin:26px 0 10px; }
.tablewrap { overflow-x:auto; border:1px solid var(--border); border-radius:10px; background:var(--surface); }
table { border-collapse:collapse; width:100%; font-size:13.5px; }
th { text-align:left; font-size:11.5px; text-transform:uppercase; letter-spacing:.04em;
  color:var(--muted); font-weight:600; padding:9px 12px; border-bottom:1px solid var(--rule);
  white-space:nowrap; }
td { padding:9px 12px; border-bottom:1px solid var(--grid); vertical-align:middle; }
tr:last-child td { border-bottom:none; }
td.num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }

button:focus-visible, input:focus-visible, summary:focus-visible, a:focus-visible {
  outline:2px solid var(--accent); outline-offset:2px; }
.hidden { display:none !important; }
footer { margin-top:32px; padding-top:12px; border-top:1px solid var(--grid);
  font-size:11.5px; color:var(--muted); }
footer code, code { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
"""


def page(title: str, extra_css: str, body_html: str, script: str = "") -> str:
    """토큰 + 기본 CSS + 페이지별 CSS 를 합쳐 아티팩트용 HTML 조각을 만든다."""
    tail = f"<script>{script}</script>" if script else ""
    return (
        f"<title>{title}</title>\n"
        f"<style>{TOKENS}{BASE}{extra_css}</style>\n"
        f'<div class="wrap">{body_html}</div>\n{tail}'
    )
