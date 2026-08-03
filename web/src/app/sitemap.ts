import type { MetadataRoute } from 'next';
import { fetchCategories } from '@/lib/db';
import { SITE_URL, isPublic } from '@/lib/site';

export const revalidate = 7200;

/**
 * 색인을 막는 동안에는 사이트맵도 비운다 — robots 와 신호가 어긋나면 안 된다.
 *
 * 채널 상세는 사이트맵에 넣지 않는다. 90개가 보드 구성에 따라 계속 바뀌는데,
 * 그때마다 사이트맵이 요동치면 크롤러에 잡음만 준다. 홈에서 링크로 도달 가능하다.
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  if (!isPublic()) return [];

  const now = new Date();
  const base: MetadataRoute.Sitemap = [
    { url: `${SITE_URL}/`, lastModified: now, changeFrequency: 'hourly', priority: 1 },
  ];

  try {
    const categories = await fetchCategories();
    for (const c of categories) {
      for (const format of ['long', 'short'] as const) {
        base.push({
          url: `${SITE_URL}/?category=${c.id}&format=${format}`,
          lastModified: now,
          changeFrequency: 'hourly',
          priority: 0.8,
        });
      }
    }
  } catch {
    // DB 장애 시 홈만이라도 남긴다 (사이트맵 500 은 크롤러에 나쁜 신호다)
  }
  return base;
}
