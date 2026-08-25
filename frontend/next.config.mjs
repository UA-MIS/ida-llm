/**
 * ⚠ `output: "standalone"` IS LOAD-BEARING. The Dockerfile copies
 * `.next/standalone` into a slim runtime image; without this setting that
 * directory is never produced and the image build fails at the COPY with a
 * confusing "not found" rather than an obvious misconfiguration.
 *
 * Note the standalone server reads HOSTNAME (not HOST) for its bind address --
 * the chart sets HOSTNAME=0.0.0.0 on this Deployment for exactly that reason. A
 * loopback bind is invisible to both kube-proxy and the kubelet's probes.
 */
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
};

export default nextConfig;
