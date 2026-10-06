import type { NextConfig } from "next";

// 브라우저는 항상 같은 출처의 /api 로 요청하고, Next 가 API 서버로 넘긴다.
// 세션 쿠키를 같은 출처로 유지하기 위한 구성이다.
const apiOrigin = process.env.API_ORIGIN ?? "http://localhost:58000";

const nextConfig: NextConfig = {
  output: "standalone",
  // 개발용 표시 아이콘이 모바일 하단 내비게이션을 가린다.
  devIndicators: false,
  experimental: {
    // 원문 PDF 업로드가 이 프록시를 지난다. 기본 한도(10MB)를 넘으면 본문이 잘려 요청이 멈춘다.
    // API 의 업로드 한도(PM_MAX_UPLOAD_MB, 기본 50MB)보다 조금 크게 둔다.
    proxyClientMaxBodySize: "64mb",
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

export default nextConfig;
