/** @type {import('next').NextConfig} */
const nextConfig = {
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: true },
  images: { unoptimized: true },
  devIndicators: false,
  output: 'standalone',
  outputFileTracingRoot: process.cwd(),
}

export default nextConfig
