/** @type {import('next').NextConfig} */
// STATIC_EXPORT=1 (lo usa el Dockerfile): el frontend se exporta como sitio estático en out/ y el backend FastAPI lo
// sirve en la misma URL que la API (despliegue de un solo servicio). Las llamadas /api son del mismo origen.
const staticExport = process.env.STATIC_EXPORT === "1";

// Desarrollo local: /api se reenvía al backend. 127.0.0.1 y no localhost: en Windows "localhost" resuelve primero por
// IPv6 y suma ~200 ms por llamada. Con NEXT_PUBLIC_API_BASE_URL el navegador llama directo al backend (lib/api.ts).
const backendUrl = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig = staticExport
  ? { reactStrictMode: true, output: "export" }
  : {
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
