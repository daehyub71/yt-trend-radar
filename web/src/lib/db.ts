import type {
  BoardKind,
  Category,
  Channel,
  ChannelSnapshot,
  TrendScore,
  VideoFormat,
} from './types';

/**
 * Supabase PostgREST 읽기 전용 클라이언트.
 *
 * ⚠️ **anon 키만 사용한다.** 이 키는 RLS 로 읽기만 허용되며, 쓰기 시도는 401 로 막힌다
 * (verify_rls.py 13/13 검증). 쓰기 권한이 있는 service 키는 수집기(서버)에만 존재하며
 * 이 패키지는 그 이름조차 참조하지 않는다.
 *
 * 호출은 서버 컴포넌트에서만 일어난다(ISR). 브라우저 번들에 URL·키가 실리지 않도록
 * `NEXT_PUBLIC_` 접두어를 쓰지 않는다.
 */
const URL_BASE = process.env.SUPABASE_URL ?? '';
const ANON_KEY = process.env.SUPABASE_ANON_KEY ?? '';

/** 수집이 하루 3회이므로 8시간마다 재생성하면 충분하다. 조금 짧게 잡아 지연을 흡수한다. */
export const REVALIDATE_SECONDS = 60 * 60 * 2;

export class DbUnavailableError extends Error {}

async function get<T>(path: string): Promise<T[]> {
  if (!URL_BASE || !ANON_KEY) {
    throw new DbUnavailableError('SUPABASE_URL / SUPABASE_ANON_KEY 가 설정되지 않았습니다');
  }
  const res = await fetch(`${URL_BASE}/rest/v1/${path}`, {
    headers: { apikey: ANON_KEY, Authorization: `Bearer ${ANON_KEY}` },
    next: { revalidate: REVALIDATE_SECONDS },
  });
  if (!res.ok) {
    // 응답 본문에 키가 실릴 수 있으므로 상태 코드만 노출한다.
    throw new DbUnavailableError(`PostgREST ${res.status} (${path.split('?')[0]})`);
  }
  return (await res.json()) as T[];
}

export async function fetchCategories(): Promise<Category[]> {
  return get<Category>('ytr_categories?select=id,name,sort_order&order=sort_order.asc');
}

export async function fetchBoard(opts: {
  categoryId: string;
  scope: 'video' | 'channel';
  kind: BoardKind;
  format?: VideoFormat;
  limit?: number;
}): Promise<TrendScore[]> {
  const { categoryId, scope, kind, format, limit = 24 } = opts;
  const parts = [
    'select=*',
    `category_id=eq.${encodeURIComponent(categoryId)}`,
    `scope=eq.${scope}`,
    `kind=eq.${kind}`,
    format ? `format=eq.${format}` : 'format=is.null',
    'order=rank.asc',
    `limit=${limit}`,
  ];
  return get<TrendScore>(`ytr_trend_scores?${parts.join('&')}`);
}

export async function fetchChannel(channelId: string): Promise<Channel | null> {
  const rows = await get<Channel>(
    `ytr_channels?select=*&id=eq.${encodeURIComponent(channelId)}&limit=1`,
  );
  return rows[0] ?? null;
}

export async function fetchChannelSnapshots(channelId: string): Promise<ChannelSnapshot[]> {
  return get<ChannelSnapshot>(
    `ytr_channel_snapshots?select=ts,subscriber_count,view_count` +
      `&channel_id=eq.${encodeURIComponent(channelId)}&order=ts.asc`,
  );
}

/** 채널 상세에 띄울 그 채널의 급상승 영상 (보드에 오른 것 중). */
export async function fetchChannelHighlights(channelId: string): Promise<TrendScore[]> {
  return get<TrendScore>(
    `ytr_trend_scores?select=*&scope=eq.video` +
      `&channel_id=eq.${encodeURIComponent(channelId)}&order=rank.asc&limit=8`,
  );
}

/** 마지막 수집 시각 — 푸터의 "언제 기준" 표기에 쓴다. */
export async function fetchLastCollectedAt(): Promise<string | null> {
  const rows = await get<{ ts: string }>(
    'ytr_video_snapshots?select=ts&order=ts.desc&limit=1',
  );
  return rows[0]?.ts ?? null;
}
