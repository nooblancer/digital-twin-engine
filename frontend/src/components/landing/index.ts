/**
 * Landing page components barrel file.
 *
 * HeroParticles and LiveDemoPreview are loaded dynamically (no SSR) since
 * they rely on browser-only APIs (canvas, WebSocket, IntersectionObserver).
 */
import dynamic from "next/dynamic";

export const HeroParticles = dynamic(
  () => import("./HeroParticles"),
  { ssr: false }
);

export const LiveDemoPreview = dynamic(
  () =>
    import("./LiveDemoPreview").then((mod) => ({
      default: mod.LiveDemoPreview,
    })),
  { ssr: false }
);

export { AnimatedPipeline } from "./AnimatedPipeline";
export { BeforeAfterChart } from "./BeforeAfterChart";
export { StatsCounter } from "./StatsCounter";
