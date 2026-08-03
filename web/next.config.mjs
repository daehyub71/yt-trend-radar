/** @type {import('next').NextConfig} */
// ISR 서버 렌더링 (DESIGN §6, 결정 2026-08-03).
// 정적 export 를 쓰지 않는 이유: 검색 유입이 중요한 서비스라 서버가 내용을 렌더해야 하고,
// 수집 주기(하루 3회)에 맞춰 재생성되어야 한다.
const nextConfig = {
  images: {
    // 유튜브 썸네일은 원본 CDN 을 그대로 참조한다 (ToS: 재호스팅·가공 금지).
    // 그래서 Next 이미지 최적화를 끄고 <img> 로 직접 건다 — remotePatterns 는 두지 않는다.
    unoptimized: true,
  },
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
