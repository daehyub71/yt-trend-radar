import type { Metadata } from 'next';
import { SITE_NAME, SITE_URL, isPublic } from '@/lib/site';
import './globals.css';

const DESCRIPTION =
  '음식·여행·IT·바이브코딩·브이로그·운동 카테고리별로 지금 뜨는 영상과 새로 뜨는 유튜버를 찾아줍니다. 조회수 증가 속도를 직접 계산합니다.';

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: `${SITE_NAME} — 카테고리별 급상승 영상·유튜버`,
    template: `%s | ${SITE_NAME}`,
  },
  description: DESCRIPTION,
  openGraph: {
    type: 'website',
    siteName: SITE_NAME,
    locale: 'ko_KR',
    title: `${SITE_NAME} — 카테고리별 급상승 영상·유튜버`,
    description: DESCRIPTION,
    url: SITE_URL,
  },
  twitter: { card: 'summary_large_image', title: SITE_NAME, description: DESCRIPTION },
  // 콜드스타트 중에는 색인을 막는다 (lib/site.ts 참조). robots.ts 와 신호를 일치시킨다.
  robots: isPublic()
    ? { index: true, follow: true }
    : { index: false, follow: false, nocache: true },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <head>
        {/* 한글 본문용 Pretendard. 실패해도 globals.css 의 시스템 폰트로 떨어진다. */}
        <link
          rel="stylesheet"
          href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css"
        />
      </head>
      <body>
        <div className="wrap">{children}</div>
      </body>
    </html>
  );
}
