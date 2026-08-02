/** @type {import("next").NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/proxy/:path*",
        destination: `${process.env.PYTHON_SERVICE_URL || "http://localhost:8000"}/:path*`,
      },
    ];
  },
};

export default nextConfig;
