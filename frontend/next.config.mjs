/** @type {import('next').NextConfig} */
// 127.0.0.1 y no localhost: en Windows "localhost" resuelve primero por IPv6 y suma ~200 ms por llamada.
const backendUrl = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  experimental: {
    // El procesamiento con LLM de un deal puede tardar varios minutos (con un modelo local, decenas).
    proxyTimeout: 1_800_000,
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
};

export default nextConfig;
