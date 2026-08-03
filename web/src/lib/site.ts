/** 사이트 수준 설정. 배포 환경에서 환경변수로 조정한다. */

export const SITE_URL = (process.env.SITE_URL ?? 'https://yt-trend-radar.vercel.app').replace(
  /\/$/,
  '',
);

export const SITE_NAME = '뜨는유튜브';

/**
 * 검색 색인 허용 여부.
 *
 * 기본값은 **비공개**다. 콜드스타트 중 얇은 보드가 색인되면 첫인상이 굳어버리기 때문에,
 * 데이터가 충분히 쌓였다고 판단했을 때 명시적으로 켠다 (`SITE_PUBLIC=true`).
 */
export function isPublic(): boolean {
  return (process.env.SITE_PUBLIC ?? '').toLowerCase() === 'true';
}
