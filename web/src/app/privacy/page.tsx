import Link from 'next/link';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: '개인정보처리방침',
  robots: { index: false, follow: true },
};

export default function Privacy() {
  return (
    <>
      <header className="site-head">
        <h1>개인정보처리방침</h1>
        <p>최종 갱신: 2026-08-03</p>
      </header>

      <section style={{ display: 'grid', gap: 18, fontSize: 14.5, lineHeight: 1.75 }}>
        <div>
          <h2 style={{ fontSize: 16 }}>수집하지 않는 정보</h2>
          <p style={{ color: 'var(--ink-2)' }}>
            이 서비스는 <b>회원가입과 로그인이 없으며</b>, 이름·이메일·전화번호·주소 등 개인을
            식별할 수 있는 정보를 일절 수집하지 않습니다. 쿠키를 이용한 행태 정보 수집이나 광고
            추적도 하지 않습니다.
          </p>
        </div>

        <div>
          <h2 style={{ fontSize: 16 }}>다루는 정보</h2>
          <p style={{ color: 'var(--ink-2)' }}>
            유튜브가 공개하는 채널·영상 정보(채널명, 영상 제목, 조회수, 구독자 수, 썸네일 주소)만
            다룹니다. 모두 누구나 볼 수 있는 공개 정보이며, 특정 개인의 시청 기록과는 무관합니다.
          </p>
        </div>

        <div>
          <h2 style={{ fontSize: 16 }}>보관 기간</h2>
          <p style={{ color: 'var(--ink-2)' }}>
            수집한 통계는 <b>30일 이내</b>에 갱신되거나 삭제됩니다. YouTube API 서비스 약관의
            데이터 보관 규정을 따르며, 삭제는 수집 주기마다 자동으로 실행됩니다.
          </p>
        </div>

        <div>
          <h2 style={{ fontSize: 16 }}>순위 산정</h2>
          <p style={{ color: 'var(--ink-2)' }}>
            표시되는 순위는 <b>이 서비스가 자체적으로 산출한 지표</b>입니다. 유튜브가 제공하는 공식
            순위가 아니며, 공개된 조회수·구독자 수의 증가 속도를 계산해 매깁니다.
          </p>
        </div>

        <div>
          <h2 style={{ fontSize: 16 }}>제3자 제공</h2>
          <p style={{ color: 'var(--ink-2)' }}>
            수집한 정보를 제3자에게 판매하거나 제공하지 않습니다. 다만 페이지를 표시하는 과정에서
            아래 외부 서버로 요청이 발생하며, 이때 접속 IP 등 통신에 필요한 정보가 해당 서버에
            전달됩니다.
          </p>
          <ul style={{ color: 'var(--ink-2)', marginTop: 8, paddingLeft: 20 }}>
            <li>
              <b>YouTube</b> — 영상·채널 썸네일 이미지, 영상 재생 링크
            </li>
            <li>
              <b>jsDelivr</b> — 한글 본문 서체(Pretendard) 배포
            </li>
            <li>
              <b>Vercel</b> — 이 사이트의 호스팅
            </li>
          </ul>
          <p style={{ color: 'var(--ink-2)', marginTop: 8 }}>
            이들 요청에는 이 서비스가 만든 식별자나 추적 정보가 포함되지 않습니다.
          </p>
        </div>

        <div>
          <h2 style={{ fontSize: 16 }}>문의</h2>
          <p style={{ color: 'var(--ink-2)' }}>
            <a
              href="https://github.com/daehyub71/yt-trend-radar/issues"
              target="_blank"
              rel="noopener"
              style={{ textDecoration: 'underline' }}
            >
              GitHub 이슈
            </a>
            로 문의해 주세요.
          </p>
        </div>
      </section>

      <Link className="backlink" href="/">
        ← 돌아가기
      </Link>
    </>
  );
}
