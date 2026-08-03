import { absoluteTime, formatRelative } from '@/lib/format';

/**
 * DESIGN §6.8 (ToS 표기) — 데이터 출처, 자체 지표 고지, 갱신 시각.
 * 이 고지는 선택이 아니라 준수 항목이다.
 */
export function SiteFooter({ lastCollectedAt }: { lastCollectedAt: string | null }) {
  return (
    <footer className="site-foot">
      <div>
        순위는 <b>자체 산출 급상승 지표</b>입니다 — 유튜브가 제공하는 공식 순위가 아닙니다.
        일정 주기로 수집한 공개 조회수·구독자 수의 <b>증가 속도</b>를 계산해 매깁니다.
      </div>
      <div>
        영상·채널 정보 출처: YouTube. 재생은 유튜브에서 이루어집니다.
        {lastCollectedAt ? (
          <>
            {' '}
            · 마지막 수집{' '}
            <span title={absoluteTime(lastCollectedAt)}>{formatRelative(lastCollectedAt)}</span>
          </>
        ) : null}
      </div>
      <div>
        <a href="/privacy">개인정보처리방침</a>
        {' · '}
        <a href="https://github.com/daehyub71/yt-trend-radar" target="_blank" rel="noopener">
          소스코드
        </a>
      </div>
    </footer>
  );
}
