// DB 행과 1:1 대응. trend_scores 는 조인 없이 카드를 그릴 수 있도록 비정규화돼 있다.

export type BoardScope = 'video' | 'channel';
export type BoardKind = 'trending' | 'rising';
export type VideoFormat = 'long' | 'short';

export interface TrendScore {
  scope: BoardScope;
  kind: BoardKind;
  category_id: string;
  region: string | null;
  format: VideoFormat | null;
  rank: number;
  score: number;
  target_id: string;
  title: string | null;
  channel_id: string | null;
  channel_title: string | null;
  thumbnail_url: string | null;
  published_at: string | null;
  view_count: number | null;
  subscriber_count: number | null;
  delta_views: number | null;
  window_hours: number | null;
}

export interface Category {
  id: string;
  name: string;
  sort_order: number;
}

export interface Channel {
  id: string;
  title: string;
  handle: string | null;
  thumbnail_url: string | null;
  category_id: string | null;
  subscriber_count: number | null;
  view_count: number | null;
  video_count: number | null;
}

export interface ChannelSnapshot {
  ts: string;
  subscriber_count: number | null;
  view_count: number | null;
}
