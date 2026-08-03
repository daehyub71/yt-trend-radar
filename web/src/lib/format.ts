/** 표시용 포맷터. 화면 문구 규칙은 docs/DESIGN.md §6.7 이 소유한다. */

/** 12345 → "1.2만" · 987 → "987". 한국어 사용자가 자연스럽게 읽는 단위로 끊는다. */
export function formatCount(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  if (n >= 100_000_000) return `${trimZero(n / 100_000_000)}억`;
  if (n >= 10_000) return `${trimZero(n / 10_000)}만`;
  if (n >= 1_000) return `${trimZero(n / 1_000)}천`;
  return n.toLocaleString('ko-KR');
}

function trimZero(v: number): string {
  const s = v >= 100 ? v.toFixed(0) : v.toFixed(1);
  return s.endsWith('.0') ? s.slice(0, -2) : s;
}

/** 산출 구간을 사람 말로. 48.3 → "48시간" · 168 → "7일" */
export function formatWindow(hours: number | null | undefined): string {
  if (!hours) return '';
  if (hours >= 48) return `${Math.round(hours / 24)}일`;
  return `${Math.round(hours)}시간`;
}

/** 상대 시각. title 속성에는 절대 시각을 남긴다 (DESIGN §6.7). */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const mins = Math.max(0, Math.round((Date.now() - then) / 60_000));
  if (mins < 60) return `${mins}분 전`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}시간 전`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}일 전`;
  return `${Math.round(days / 30)}개월 전`;
}

export function absoluteTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('ko-KR');
}

export const youtubeVideoUrl = (id: string) => `https://www.youtube.com/watch?v=${id}`;
export const youtubeChannelUrl = (id: string) => `https://www.youtube.com/channel/${id}`;
