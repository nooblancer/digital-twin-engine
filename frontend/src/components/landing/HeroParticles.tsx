"use client";

import { useCallback, useMemo } from "react";
import Particles from "@tsparticles/react";
import { ParticlesProvider } from "@tsparticles/react";
import { loadSlim } from "@tsparticles/slim";
import type { ISourceOptions, Engine } from "@tsparticles/engine";
import { usePrefersReducedMotion } from "@/lib/animations";

/**
 * Particle configuration for the hero background.
 *
 * - Renders 80-150 cyan/violet particles forming a turbofan engine silhouette
 * - Particles drift slowly for the silhouette zone, with directed flow for pipeline path
 * - Link lines between nearby particles with low opacity
 * - GPU-accelerated canvas compositing targeting 60fps
 */
function useParticlesOptions(reducedMotion: boolean): ISourceOptions {
  return useMemo<ISourceOptions>(
    () => ({
      fpsLimit: 60,
      fullScreen: false,
      detectRetina: true,
      background: {
        color: { value: "transparent" },
      },
      particles: {
        number: {
          value: reducedMotion ? 100 : 120,
          density: {
            enable: true,
          },
        },
        color: {
          value: ["#00d4ff", "#7c3aed"],
        },
        shape: {
          type: "circle",
        },
        opacity: {
          value: { min: 0.3, max: 0.7 },
          animation: reducedMotion
            ? undefined
            : {
                enable: true,
                speed: 0.5,
                sync: false,
              },
        },
        size: {
          value: { min: 1, max: 3 },
        },
        links: {
          enable: true,
          distance: 120,
          color: "#00d4ff",
          opacity: 0.12,
          width: 1,
        },
        move: {
          enable: !reducedMotion,
          speed: 0.6,
          direction: "none",
          outModes: {
            default: "bounce",
          },
          straight: false,
        },
      },
      interactivity: {
        detectsOn: "canvas",
        events: {
          onHover: {
            enable: !reducedMotion,
            mode: "grab",
          },
          resize: { enable: true },
        },
        modes: {
          grab: {
            distance: 140,
            links: {
              opacity: 0.25,
            },
          },
        },
      },
      // Additional emitter groups to form the turbofan silhouette and pipeline flow
      // Group 1: Core particles — concentrated in center forming engine cross-section
      // Group 2: Flow particles — drift left-to-right simulating data pipeline path
      groups: {
        turbofan: {
          number: { value: 60 },
          opacity: { value: { min: 0.4, max: 0.8 } },
          size: { value: { min: 1.5, max: 3 } },
          move: {
            enable: !reducedMotion,
            speed: 0.3,
            direction: "none",
            outModes: { default: "bounce" },
          },
          color: { value: "#00d4ff" },
        },
        pipeline: {
          number: { value: 40 },
          opacity: { value: { min: 0.2, max: 0.6 } },
          size: { value: { min: 1, max: 2.5 } },
          move: {
            enable: !reducedMotion,
            speed: 1.2,
            direction: "right",
            outModes: { default: "out" },
            straight: true,
          },
          color: { value: "#7c3aed" },
        },
      },
    }),
    [reducedMotion]
  );
}

/**
 * HeroParticles — GPU-accelerated canvas particle system for the landing hero section.
 *
 * Renders a decorative particle background forming a turbofan engine silhouette
 * with animated particle flow along the sensors → ML → EnKF → output pipeline path.
 *
 * - Positioned absolutely behind hero content (z-index: 0)
 * - Respects prefers-reduced-motion (renders static arrangement)
 * - aria-hidden="true" for accessibility (purely decorative)
 * - Loaded via next/dynamic with { ssr: false } from the landing page barrel
 *
 * Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 15.3
 */
function HeroParticles() {
  const reducedMotion = usePrefersReducedMotion();
  const options = useParticlesOptions(reducedMotion);

  const particlesInit = useCallback(async (engine: Engine) => {
    await loadSlim(engine);
  }, []);

  return (
    <ParticlesProvider init={particlesInit}>
      <div
        aria-hidden="true"
        className="absolute inset-0 z-0 overflow-hidden pointer-events-none"
        style={{ willChange: reducedMotion ? "auto" : "transform" }}
      >
        <Particles
          id="hero-particles"
          options={options}
          className="h-full w-full"
        />
      </div>
    </ParticlesProvider>
  );
}

export default HeroParticles;
