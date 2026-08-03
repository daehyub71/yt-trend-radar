import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: {
    default: '뜨는유튜브 — 카테고리별 급상승 영상·유튜버',
    template: '%s | 뜨는유튜브',
  },
  description:
    '음식·여행·IT·바이브코딩·브이로그·운동 카테고리별로 지금 뜨는 영상과 새로 뜨는 유튜버를 찾아줍니다. 조회수 증가 속도를 직접 계산합니다.',
  openGraph: {
    type: 'website',
    siteName: '뜨는유튜브',
    locale: 'ko_KR',
  },
  robots: { index: true, follow: true },
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
