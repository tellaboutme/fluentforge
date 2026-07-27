/** @type {import('next').NextConfig} */
const nextConfig = {
  // Playwright browses via 127.0.0.1 while the dev server considers its own
  // origin to be localhost. Next 16 blocks cross-origin dev resources by
  // default, which silently prevented hydration under test: the register
  // form fell back to a native GET submit, putting the password in the URL
  // and stranding every journey on /register. Dev-only; production builds
  // do not read this setting.
  allowedDevOrigins: ["127.0.0.1"],

  reactStrictMode: true,
  // The contracts package ships TypeScript source, not a build artifact, so the
  // API shape stays a single source of truth with no build step to forget.
  transpilePackages: ["@fluentforge/contracts"],
};

export default nextConfig;
