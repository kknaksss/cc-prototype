import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // 배포 이미지(Dockerfile) — node server.js 하나로 뜨는 최소 묶음
  output: 'standalone',
  agentRules: false,
};

export default nextConfig;
