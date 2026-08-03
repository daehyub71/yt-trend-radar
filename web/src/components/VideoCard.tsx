import Link from 'next/link';
import type { TrendScore } from '@/lib/types';
import {
  absoluteTime,
  formatCount,
  formatRelative,
  formatWindow,
  youtubeVideoUrl,
} from '@/lib/format';

/**
 * 영상 카드.
 *
 * DESIGN §6.3: **원시 점수를 노출하지 않는다.** 대신 검증 가능한 사실
 * (구간 내 조회수 증가량)을 주 표기로 쓰고, 보드 1위 대비 상대 강도를 막대로 보조한다.
 *
 * 구조 주의: 카드 전체를 `<a>` 로 감싸면 채널 링크가 앵커 중첩이 되어 **유효하지 않은 HTML**
 * 이 된다(브라우저가 임의로 교정하고, 스크린리더도 오작동한다). 그래서 카드는 컨테이너로 두고
 * 썸네일·제목·채널을 각각 독립 링크로 만든다.
 */
export function VideoCard({ row, topDelta }: { row: TrendScore; topDelta: number }) {
  const gain = row.delta_views ?? 0;
  const ratio = topDelta > 0 ? Math.max(0.04, gain / topDelta) : 0;
  const title = row.title ?? '(제목 없음)';
  const url = youtubeVideoUrl(row.target_id);

  return (
    <article className="card">
      <a className="thumb" href={url} target="_blank" rel="noopener" tabIndex={-1} aria-hidden="true">
        {row.thumbnail_url ? (
          // 유튜브 CDN 원본을 그대로 참조한다 (ToS: 재호스팅·가공 금지)
          // eslint-disable-next-line @next/next/no-img-element
          <img src={row.thumbnail_url} alt="" loading="lazy" decoding="async" />
        ) : null}
        <span className="rank" data-top={row.rank <= 3 ? row.rank : undefined}>
          {row.rank}
        </span>
      </a>

      <div className="body">
        <a className="title" href={url} target="_blank" rel="noopener">
          {title}
        </a>

        <div className="meta">
          {row.channel_id ? (
            <Link className="ch" href={`/channel/${row.channel_id}`}>
              {row.channel_title ?? '채널'}
            </Link>
          ) : (
            (row.channel_title ?? '')
          )}
          {row.view_count != null ? ` · 조회 ${formatCount(row.view_count)}` : ''}
          {row.published_at ? (
            <span title={absoluteTime(row.published_at)}> · {formatRelative(row.published_at)}</span>
          ) : null}
        </div>

        <div className="gain">
          <span
            className="gainbar"
            role="img"
            aria-label={`상대 상승폭 ${Math.round(ratio * 100)}%`}
          >
            <i style={{ width: `${Math.round(ratio * 100)}%` }} />
          </span>
          <span className="num">
            {formatWindow(row.window_hours)} +{formatCount(gain)}
          </span>
        </div>
      </div>
    </article>
  );
}
