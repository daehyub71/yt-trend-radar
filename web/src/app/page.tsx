import Link from 'next/link';
import { DbUnavailableError, fetchBoard, fetchCategories, fetchLastCollectedAt } from '@/lib/db';
import type { VideoFormat } from '@/lib/types';
import { ChannelBoard, VideoBoard } from '@/components/Board';
import { SiteFooter } from '@/components/SiteFooter';

// Next 는 이 값을 정적 분석하므로 **리터럴이어야 한다** (import 한 식별자는 인식하지 못한다).
// 2시간 = 수집 주기(하루 3회, 8시간)보다 짧게 잡아 cron 지연을 흡수한다.
// lib/db.ts 의 REVALIDATE_SECONDS 와 같은 값으로 유지할 것.
export const revalidate = 7200;

type Search = { [k: string]: string | string[] | undefined };

export default async function Home({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const format: VideoFormat = sp.format === 'short' ? 'short' : 'long';

  let categories;
  try {
    categories = await fetchCategories();
  } catch (e) {
    // DB 장애로 페이지가 통째로 죽지 않게 한다 (SPEC NFR-9 와 같은 취지).
    // 원인을 못 좁히는 오류 화면은 없느니만 못하므로, **키 값이 아닌 사유**를 함께 보여준다.
    const detail =
      e instanceof DbUnavailableError
        ? e.reason === 'missing-config'
          ? '서버에 데이터베이스 접속 설정이 없습니다.'
          : e.reason === 'network'
            ? '데이터베이스에 연결하지 못했습니다.'
            : `데이터베이스가 ${e.status} 응답을 보냈습니다.`
        : null;
    return (
      <>
        <Head />
        <p className="empty">
          지금은 데이터를 불러올 수 없습니다. 잠시 후 다시 시도해 주세요.
          {detail ? (
            <>
              <br />
              <span style={{ color: 'var(--muted)', fontSize: 12.5 }}>
                {detail} 진단: <code>/api/health</code>
              </span>
            </>
          ) : null}
        </p>
        <SiteFooter lastCollectedAt={null} />
      </>
    );
  }

  const current =
    categories.find((c) => c.id === sp.category) ?? categories[0] ?? { id: '', name: '' };

  const [trendingVideos, risingVideos, trendingChannels, risingChannels, lastCollectedAt] =
    await Promise.all([
      fetchBoard({ categoryId: current.id, scope: 'video', kind: 'trending', format }),
      fetchBoard({ categoryId: current.id, scope: 'video', kind: 'rising', format }),
      fetchBoard({ categoryId: current.id, scope: 'channel', kind: 'trending', limit: 12 }),
      fetchBoard({ categoryId: current.id, scope: 'channel', kind: 'rising', limit: 12 }),
      fetchLastCollectedAt(),
    ]);

  const q = (over: Record<string, string>) => {
    const p = new URLSearchParams({ category: current.id, format, ...over });
    return `/?${p.toString()}`;
  };

  return (
    <>
      <Head />

      <nav className="chipbar" aria-label="카테고리">
        {categories.map((c) => (
          <Link
            key={c.id}
            className="chip"
            href={`/?category=${c.id}&format=${format}`}
            aria-current={c.id === current.id ? 'page' : undefined}
          >
            {c.name}
          </Link>
        ))}
      </nav>

      <div className="toolbar">
        <div className="seg" role="group" aria-label="영상 형식">
          <Link href={q({ format: 'long' })} aria-current={format === 'long' ? 'page' : undefined}>
            롱폼
          </Link>
          <Link href={q({ format: 'short' })} aria-current={format === 'short' ? 'page' : undefined}>
            Shorts
          </Link>
        </div>
        <span className="hint">
          Shorts 는 조회수가 오르는 속도가 달라 롱폼과 따로 집계합니다
        </span>
      </div>

      <div className="boards two">
        <VideoBoard kind="trending" format={format} rows={trendingVideos} />
        <VideoBoard kind="rising" format={format} rows={risingVideos} />
      </div>

      <div className="boards two" style={{ marginTop: 30 }}>
        <ChannelBoard kind="trending" rows={trendingChannels} />
        <ChannelBoard kind="rising" rows={risingChannels} />
      </div>

      <SiteFooter lastCollectedAt={lastCollectedAt} />
    </>
  );
}

function Head() {
  return (
    <header className="site-head">
      <h1>지금 뜨는 유튜브</h1>
      <p>카테고리별로 조회수가 빠르게 오르는 영상과, 규모 대비 두드러진 채널을 찾아줍니다.</p>
    </header>
  );
}
