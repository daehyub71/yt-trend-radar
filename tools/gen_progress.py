# -*- coding: utf-8 -*-
"""docs/TASK.md → docs/progress.html 진행 대시보드 생성기.

SDD 규칙 4 (워크스페이스 CLAUDE.md): Phase 완료마다 실행하고 아티팩트로 게시한다.

색 토큰은 `_theme.TOKENS` 에서 가져온다 — 세 생성기가 각자 선언하면 반드시 어긋난다.
레이아웃 CSS 는 페이지마다 형태가 달라 각자 갖는다(여긴 920px, 콘솔·검토는 1040px).
값의 근거와 검증 기록은 `docs/DESIGN.md` 소관.

사용법:  python tools/gen_progress.py   (프로젝트 루트 또는 아무 데서나)
"""
import html
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _theme import TOKENS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TASK_MD = ROOT / "docs" / "TASK.md"
OUT_HTML = ROOT / "docs" / "progress.html"

# 마일스톤 ↔ Phase 매핑 (PLAN.md §5)
MILESTONES = [
    ("M1", "로컬 harness GREEN", ["P0", "P1", "P2"]),
    ("M2", "Actions cron 가동·콜드스타트 시작", ["P3", "P4"]),
    ("M3", "UI 완성 (DESIGN 검증 포함)", ["P5"]),
    ("M4", "보안 검토 통과 → 공개 배포", ["P6"]),
    ("M5", "운영 체계 (콘솔·런북·알림)", ["P7"]),
]

PHASE_RE = re.compile(r"^## (P\d)\. (.+)$")
TASK_RE = re.compile(r"^- \[( |x)\] (.+)$")
DONE_ROW_RE = re.compile(r"^\| (P\d) \| (.+?) \|$")


def parse_task_md(text: str):
    phases = []  # {id, title, tasks: [(done, label)], done_at}
    current = None
    done_dates = {}
    for line in text.splitlines():
        m = PHASE_RE.match(line)
        if m:
            current = {"id": m.group(1), "title": m.group(2), "tasks": [], "done_at": None}
            phases.append(current)
            continue
        if line.startswith("## "):  # 완료 기록 등 비-Phase 섹션
            current = None
            continue
        m = TASK_RE.match(line)
        if m and current is not None:
            current["tasks"].append((m.group(1) == "x", m.group(2)))
            continue
        m = DONE_ROW_RE.match(line)
        if m and m.group(2).strip():
            done_dates[m.group(1)] = m.group(2).strip()
    for p in phases:
        p["done_at"] = done_dates.get(p["id"])
    return phases


def phase_status(p):
    """완료 판정은 체크박스가 기준이다.

    완료 기록표의 날짜는 참고용일 뿐 — 미체크 태스크가 남아 있으면 '완료'로 올리지 않는다
    (날짜만으로 done 처리하면 진행률을 과장해 보고하게 된다).
    """
    total = len(p["tasks"])
    done = sum(1 for d, _ in p["tasks"] if d)
    if total > 0:
        return "done" if done == total else ("active" if done > 0 else "pending")
    return "done" if p["done_at"] else "pending"


CSS = """
body {
  background: var(--page); color: var(--ink);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  margin: 0; line-height: 1.5;
}
.wrap { max-width: 920px; margin: 0 auto; padding: 40px 20px 56px; }
header .eyebrow {
  font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--muted); font-weight: 600;
}
header h1 { margin: 4px 0 2px; font-size: 26px; text-wrap: balance; }
header .sub { color: var(--ink-2); font-size: 13.5px; margin: 0; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin: 24px 0 8px; }
.tile {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px 16px;
}
.tile .label { font-size: 12px; color: var(--muted); font-weight: 600; }
.tile .value { font-size: 26px; font-weight: 700; margin-top: 2px; }
.tile .value small { font-size: 14px; font-weight: 500; color: var(--ink-2); }
.overall { margin: 10px 0 26px; }
.bar { background: var(--grid); border-radius: 4px; height: 8px; overflow: hidden; }
.bar > i { display: block; height: 100%; background: var(--accent); border-radius: 4px; min-width: 2px; }
.bar > i.zero { min-width: 0; }
.barrow { display: flex; align-items: center; gap: 10px; }
.barrow .bar { flex: 1; }
.barrow .num { font-variant-numeric: tabular-nums; font-size: 12.5px; color: var(--ink-2); white-space: nowrap; }
section h2 { font-size: 15px; margin: 26px 0 10px; color: var(--ink); }
.phase {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px 16px; margin-bottom: 10px;
}
.phead { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.pname { font-weight: 650; font-size: 14.5px; flex: 1; }
.chip {
  font-size: 11.5px; font-weight: 650; border-radius: 999px; padding: 2px 10px;
  border: 1px solid var(--border); white-space: nowrap;
}
.chip.done   { color: var(--good-text); border-color: color-mix(in oklab, var(--good) 45%, transparent); }
.chip.active { color: var(--accent);   border-color: color-mix(in oklab, var(--accent) 45%, transparent); }
.chip.pending{ color: var(--muted); }
.pdate { font-size: 12px; color: var(--muted); white-space: nowrap; }
.phase .barrow { margin-top: 10px; }
details { margin-top: 8px; }
summary { cursor: pointer; font-size: 12.5px; color: var(--ink-2); user-select: none; }
ul.tasks { list-style: none; margin: 8px 0 2px; padding: 0; }
ul.tasks li { font-size: 13px; padding: 3px 0 3px 24px; position: relative; color: var(--ink-2); }
ul.tasks li::before {
  position: absolute; left: 2px; top: 3px; font-size: 12px;
  content: "○"; color: var(--muted);
}
ul.tasks li.done { color: var(--muted); text-decoration: line-through; text-decoration-color: var(--grid); }
ul.tasks li.done::before { content: "✓"; color: var(--good-text); font-weight: 700; }
.mstones { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; }
.ms { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; }
.ms .mtag { font-size: 12px; font-weight: 700; color: var(--accent); }
.ms .mtag.msdone { color: var(--good-text); }
.ms .mtitle { font-size: 13px; margin-top: 2px; }
.ms .mphases { font-size: 11.5px; color: var(--muted); margin-top: 4px; font-variant-numeric: tabular-nums; }
footer { margin-top: 30px; font-size: 11.5px; color: var(--muted); border-top: 1px solid var(--grid); padding-top: 12px; }
"""


def bar(done: int, total: int) -> str:
    pct = 0 if total == 0 else round(done / total * 100)
    zero = " zero" if done == 0 else ""
    return (
        f'<div class="barrow"><div class="bar" role="img" aria-label="진행률 {pct}%">'
        f'<i class="{zero.strip()}" style="width:{pct}%"></i></div>'
        f'<span class="num">{done}/{total} · {pct}%</span></div>'
    )


def render(phases) -> str:
    total_tasks = sum(len(p["tasks"]) for p in phases)
    done_tasks = sum(sum(1 for d, _ in p["tasks"] if d) for p in phases)
    done_phases = [p for p in phases if phase_status(p) == "done"]
    current = next((p for p in phases if phase_status(p) != "done"), None)
    pct = 0 if total_tasks == 0 else round(done_tasks / total_tasks * 100)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    chips = {"done": "✓ 완료", "active": "▶ 진행 중", "pending": "○ 대기"}
    phase_html = []
    for p in phases:
        st = phase_status(p)
        n_done = sum(1 for d, _ in p["tasks"] if d)
        date = f'<span class="pdate">{html.escape(p["done_at"])}</span>' if p["done_at"] else ""
        items = "".join(
            f'<li class="{"done" if d else ""}">{html.escape(label)}</li>'
            for d, label in p["tasks"]
        )
        phase_html.append(
            f'<div class="phase"><div class="phead">'
            f'<span class="pname">{p["id"]}. {html.escape(p["title"])}</span>'
            f'{date}<span class="chip {st}">{chips[st]}</span></div>'
            f"{bar(n_done, len(p['tasks']))}"
            f'<details><summary>태스크 {len(p["tasks"])}개</summary><ul class="tasks">{items}</ul></details>'
            f"</div>"
        )

    status_by_id = {p["id"]: phase_status(p) for p in phases}
    ms_html = []
    for tag, title, ids in MILESTONES:
        ms_done = all(status_by_id.get(i) == "done" for i in ids)
        mark = "✓ " if ms_done else ""
        cls = " msdone" if ms_done else ""
        ms_html.append(
            f'<div class="ms"><div class="mtag{cls}">{mark}{tag}</div>'
            f'<div class="mtitle">{html.escape(title)}</div>'
            f'<div class="mphases">{" · ".join(ids)}</div></div>'
        )

    cur_label = f'{current["id"]}. {html.escape(current["title"])}' if current else "전체 완료 🎉"
    return f"""<title>yt-trend-radar 진행 현황</title>
<style>{TOKENS}{CSS}</style>
<div class="wrap">
<header>
  <div class="eyebrow">SDD 진행 대시보드</div>
  <h1>yt-trend-radar</h1>
  <p class="sub">유튜브 카테고리별 트렌드 발견 서비스 · docs/TASK.md 기준 · 갱신 {now}</p>
</header>
<div class="tiles">
  <div class="tile"><div class="label">전체 진행률</div><div class="value">{pct}<small>%</small></div></div>
  <div class="tile"><div class="label">태스크</div><div class="value">{done_tasks}<small> / {total_tasks}</small></div></div>
  <div class="tile"><div class="label">Phase 완료</div><div class="value">{len(done_phases)}<small> / {len(phases)}</small></div></div>
  <div class="tile"><div class="label">현재 단계</div><div class="value" style="font-size:15px;line-height:1.35;margin-top:6px">{cur_label}</div></div>
</div>
<div class="overall">{bar(done_tasks, total_tasks)}</div>
<section><h2>Phase</h2>{"".join(phase_html)}</section>
<section><h2>마일스톤</h2><div class="mstones">{"".join(ms_html)}</div></section>
<footer>생성: tools/gen_progress.py · 색상: dataviz 검증 기본 팔레트 (상태는 색+아이콘+라벨 병행) · 상세 기준: docs/PLAN.md</footer>
</div>
"""


def main():
    phases = parse_task_md(TASK_MD.read_text(encoding="utf-8"))
    OUT_HTML.write_text(render(phases), encoding="utf-8")
    total = sum(len(p["tasks"]) for p in phases)
    done = sum(sum(1 for d, _ in p["tasks"] if d) for p in phases)
    print(f"OK: {OUT_HTML} ({len(phases)} phases, {done}/{total} tasks)")


if __name__ == "__main__":
    main()
