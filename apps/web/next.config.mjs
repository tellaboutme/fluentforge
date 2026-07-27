/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The contracts package ships TypeScript source, not a build artifact, so the
  // API shape stays a single source of truth with no build step to forget.
  transpilePackages: ["@fluentforge/contracts"],
};

export default nextConfig;
