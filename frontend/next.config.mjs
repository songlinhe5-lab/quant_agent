/** @type {import('next').NextConfig} */
const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  async rewrites() {
    return [
      {
        // 捕获所有以 /api/ 开头的请求，无缝转发给后端的 8000 端口
        source: '/api/:path*',
        destination: 'http://127.0.0.1:8000/api/:path*' 
      }
    ];
  },
}

export default nextConfig