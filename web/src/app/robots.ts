import type { MetadataRoute } from 'next';
import { SITE_URL, isPublic } from '@/lib/site';

/**
 * 콜드스타트 중에는 색인을 막는다.
 *
 * 속도 계산에는 같은 대상의 스냅샷이 2개 이상 필요하고, 의미 있는 순위가 나오려면
 * 2주 정도 축적이 필요하다. 그 전에 색인되면 **얇은 보드가 검색 결과의 첫인상**이 되고,
 * 이후 내용이 좋아져도 평가가 따라오지 않는다.
 *
 * 데이터가 차면 `SITE_PUBLIC=true` 로 바꾸기만 하면 된다 — 코드 변경이 아니라 설정 변경이다.
 */
export default function robots(): MetadataRoute.Robots {
  if (!isPublic()) {
    return { rules: [{ userAgent: '*', disallow: '/' }] };
  }
  return {
    rules: [{ userAgent: '*', allow: '/', disallow: ['/privacy'] }],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
