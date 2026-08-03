import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import {
  fetchChannel,
  fetchChannelHighlights,
  fetchChannelSnapshots,
  fetchLastCollectedAt,
} from '@/lib/db';
import { formatCount, youtubeChannelUrl } from '@/lib/format';
import { Sparkline } from '@/components/Sparkline';
import { VideoCard } from '@/components/VideoCard';
import { SiteFooter } from '@/components/SiteFooter';

// 리터럴이어야 한다 (Next 정적 분석). lib/db.ts 의 REVALIDATE_SECONDS 와 동일 값 유지.
export const revalidate = 7200;

type Params = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { id } = await params;
  try {
    const ch = await fetchChannel(id);
    if (!ch) return { title: '채널을 찾을 수 없습니다' };
    return {
      title: ch.title,
      description: `${ch.title} 채널의 최근 30일 구독자·조회수 추이와 급상승 영상.`,
    };
  } catch {
    return { title: '채널' };
  }
}

export default async function ChannelPage({ params }: Params) {
  const { id } = await params;

  let channel, snapshots, highlights, lastCollectedAt;
  try {
    [channel, snapshots, highlights, lastCollectedAt] = await Promise.all([
      fetchChannel(id),
      fetchChannelSnapshots(id),
      fetchChannelHighlights(id),
      fetchLastCollectedAt(),
    ]);
  } catch {
    return (
      <>
        <p className="empty">지금은 데이터를 불러올 수 없습니다. 잠시 후 다시 시도해 주세요.</p>
        <SiteFooter lastCollectedAt={null} />
      </>
    );
  }

  if (!channel) notFound();

  const topDelta = highlights[0]?.delta_views ?? 0;

  return (
    <>
      <header className="detail-head">
        {channel.thumbnail_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={channel.thumbnail_url} alt="" />
        ) : (
          <span aria-hidden="true" />
        )}
        <div>
          <h1>{channel.title}</h1>
          <div className="meta">
            구독 {formatCount(channel.subscriber_count)}
            {channel.video_count != null ? ` · 영상 ${formatCount(channel.video_count)}개` : ''}
            {channel.handle ? ` · ${channel.handle}` : ''}
          </div>
          <a
            className="backlink"
            href={youtubeChannelUrl(channel.id)}
            target="_blank"
            rel="noopener"
          >
            유튜브에서 채널 열기 →
          </a>
        </div>
      </header>

      {/* 이중 축을 쓰지 않는다 — 척도가 다른 두 값은 각각의 차트로 (DESIGN §6.6) */}
      <div className="charts">
        <Sparkline
          title="구독자 추이"
          accent="var(--trending)"
          points={snapshots.map((s) => ({ ts: s.ts, value: s.subscriber_count }))}
        />
        <Sparkline
          title="총 조회수 추이"
          accent="var(--rising)"
          points={snapshots.map((s) => ({ ts: s.ts, value: s.view_count }))}
        />
      </div>

      <section className="board" data-kind="trending">
        <header>
          <h2>
            <span className="dot" aria-hidden="true" />이 채널의 급상승 영상
          </h2>
        </header>
        {highlights.length === 0 ? (
          <p className="empty">
            현재 보드에 오른 영상이 없습니다. 수집이 쌓이면 이곳에 표시됩니다.
          </p>
        ) : (
          <div className="cards">
            {highlights.map((r) => (
              <VideoCard key={`${r.kind}-${r.format}-${r.target_id}`} row={r} topDelta={topDelta} />
            ))}
          </div>
        )}
      </section>

      <Link className="backlink" href="/">
        ← 전체 보드로
      </Link>

      <SiteFooter lastCollectedAt={lastCollectedAt} />
    </>
  );
}
