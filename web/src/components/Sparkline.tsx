import { formatCount } from '@/lib/format';

/**
 * 30일 추이 선형 차트 — DESIGN §6.6.
 *
 * form heuristic: 시간에 따른 변화 → 선형. 임의 선택이 아니다.
 * **이중 축을 쓰지 않는다** — 구독자와 조회수는 각각 별도 차트다.
 * 단일 시리즈이므로 범례를 두지 않는다(제목이 시리즈를 지칭한다).
 * 스냅샷이 2개 미만이면 그리지 않는다 — 빈 축만 있는 차트는 장애처럼 보인다.
 */
export function Sparkline({
  title,
  points,
  accent,
}: {
  title: string;
  points: { ts: string; value: number | null }[];
  accent: string;
}) {
  const usable = points.filter((p) => p.value !== null) as { ts: string; value: number }[];
  const latest = usable.at(-1)?.value ?? null;
  const first = usable[0]?.value ?? null;
  const delta = latest !== null && first !== null ? latest - first : null;

  if (usable.length < 2) {
    return (
      <div className="chart">
        <h3>{title}</h3>
        <div className="now">{latest !== null ? formatCount(latest) : '—'}</div>
        <p className="notice">데이터 축적 중입니다 — 추이를 그리려면 수집이 2회 이상 필요합니다.</p>
      </div>
    );
  }

  const W = 320;
  const H = 72;
  const PAD = 4;
  const values = usable.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;

  const x = (i: number) => PAD + (i / (usable.length - 1)) * (W - PAD * 2);
  const y = (v: number) => H - PAD - ((v - min) / span) * (H - PAD * 2);

  const line = usable.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ');
  const area = `${line} L${x(usable.length - 1).toFixed(1)},${H} L${x(0).toFixed(1)},${H} Z`;
  const lastX = x(usable.length - 1);
  const lastY = y(values[values.length - 1]);

  return (
    <div className="chart">
      <h3>{title}</h3>
      <div>
        <span className="now">{formatCount(latest)}</span>
        {delta !== null && delta !== 0 ? (
          <span className="delta">
            관측 구간 {delta > 0 ? '+' : '−'}
            {formatCount(Math.abs(delta))}
          </span>
        ) : null}
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`${title} 추이. 관측 ${usable.length}회, 최근 ${formatCount(latest)}`}
      >
        {/* 그리드는 가로선만, 헤어라인 */}
        {[0.25, 0.5, 0.75].map((f) => (
          <line
            key={f}
            x1={PAD}
            x2={W - PAD}
            y1={PAD + f * (H - PAD * 2)}
            y2={PAD + f * (H - PAD * 2)}
            stroke="var(--grid)"
            strokeWidth="1"
          />
        ))}
        <path d={area} fill={accent} opacity="0.12" />
        <path d={line} fill="none" stroke={accent} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={lastX} cy={lastY} r="3.5" fill={accent} stroke="var(--surface)" strokeWidth="2" />
      </svg>
    </div>
  );
}
