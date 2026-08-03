import Link from 'next/link';
import type { BoardKind, TrendScore, VideoFormat } from '@/lib/types';
import { formatCount, formatWindow, youtubeChannelUrl } from '@/lib/format';
import { VideoCard } from './VideoCard';

/** 화면에는 내부 용어(trending/rising)를 쓰지 않는다 — DESIGN §6.7 */
export const BOARD_TITLE: Record<string, string> = {
  'video:trending': '지금 뜨는 영상',
  'video:rising': '새로 뜨는 영상',
  'channel:trending': '지금 뜨는 유튜버',
  'channel:rising': '새로 뜨는 유튜버',
};

const BOARD_HINT: Record<string, string> = {
  'video:trending': '최근 조회수가 가장 빠르게 오른 영상',
  'video:rising': '구독자 규모 대비 성과가 두드러진 영상',
  'channel:trending': '조회수가 빠르게 늘고 있는 채널',
  'channel:rising': '구독자 10만 이하 · 성장세가 두드러진 채널',
};

function Empty({ what }: { what: string }) {
  // 사과하지 않고 이유와 다음 상태를 말한다 (DESIGN §6.7)
  return (
    <p className="empty">
      아직 이 카테고리의 <b>{what}</b>이 없습니다. 속도를 재려면 같은 대상이 두 번 이상
      수집돼야 하며, 수집이 쌓이면 채워집니다.
    </p>
  );
}

export function VideoBoard({
  kind,
  format,
  rows,
}: {
  kind: BoardKind;
  format: VideoFormat;
  rows: TrendScore[];
}) {
  const key = `video:${kind}`;
  const topDelta = rows[0]?.delta_views ?? 0;

  return (
    <section className="board" data-kind={kind}>
      <header>
        <h2>
          <span className="dot" aria-hidden="true" />
          {BOARD_TITLE[key]}
        </h2>
        <span className="sub">{BOARD_HINT[key]}</span>
      </header>
      {rows.length === 0 ? (
        <Empty what={BOARD_TITLE[key]} />
      ) : (
        <div className={format === 'short' ? 'cards shorts' : 'cards'}>
          {rows.map((r) => (
            <VideoCard key={r.target_id} row={r} topDelta={topDelta} />
          ))}
        </div>
      )}
    </section>
  );
}

export function ChannelBoard({ kind, rows }: { kind: BoardKind; rows: TrendScore[] }) {
  const key = `channel:${kind}`;
  const topDelta = rows[0]?.delta_views ?? 0;
  const unit = kind === 'rising' ? '구독자' : '조회수';

  return (
    <section className="board" data-kind={kind}>
      <header>
        <h2>
          <span className="dot" aria-hidden="true" />
          {BOARD_TITLE[key]}
        </h2>
        <span className="sub">{BOARD_HINT[key]}</span>
      </header>
      {rows.length === 0 ? (
        <Empty what={BOARD_TITLE[key]} />
      ) : (
        <div className="cards">
          {rows.map((r) => {
            const gain = r.delta_views ?? 0;
            const ratio = topDelta > 0 ? Math.max(0.04, gain / topDelta) : 0;
            return (
              <Link className="chcard" key={r.target_id} href={`/channel/${r.target_id}`}>
                {r.thumbnail_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={r.thumbnail_url} alt="" loading="lazy" decoding="async" />
                ) : (
                  <span aria-hidden="true" />
                )}
                <div>
                  <div className="title">
                    {r.rank}. {r.title ?? '(채널)'}
                  </div>
                  <div className="meta">
                    구독 {formatCount(r.subscriber_count)}
                    {' · '}
                    {formatWindow(r.window_hours)} {unit} +{formatCount(gain)}
                  </div>
                  <div className="gain">
                    <span
                      className="gainbar"
                      role="img"
                      aria-label={`상대 성장폭 ${Math.round(ratio * 100)}%`}
                    >
                      <i style={{ width: `${Math.round(ratio * 100)}%` }} />
                    </span>
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </section>
  );
}

export { youtubeChannelUrl };
