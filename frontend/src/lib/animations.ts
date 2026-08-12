"use client";

import { useState, useEffect } from "react";
import { Variants } from "framer-motion";

/**
 * Hook to detect user's reduced motion preference.
 * Returns true if the user prefers reduced motion.
 *
 * Validates: Requirements 14.4
 */
export function usePrefersReducedMotion(): boolean {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    setPrefersReducedMotion(mediaQuery.matches);

    const handleChange = (event: MediaQueryListEvent) => {
      setPrefersReducedMotion(event.matches);
    };

    mediaQuery.addEventListener("change", handleChange);
    return () => {
      mediaQuery.removeEventListener("change", handleChange);
    };
  }, []);

  return prefersReducedMotion;
}

/**
 * Spring config for counter animations (framer-motion useSpring).
 * Used by AnimatedCounter for smooth number interpolation.
 *
 * Validates: Requirements 14.2
 */
export const counterSpring = {
  type: "spring" as const,
  stiffness: 100,
  damping: 15,
  mass: 0.5,
};

/**
 * Data arrival glow variants: applied to GlowCard when new WebSocket data arrives.
 * Produces a brief cyan border glow animation lasting ~400ms.
 *
 * Validates: Requirements 14.1
 */
export const dataArrivalVariants: Variants = {
  idle: { boxShadow: "0 0 0px rgba(0, 212, 255, 0)" },
  pulse: {
    boxShadow: [
      "0 0 0px rgba(0, 212, 255, 0)",
      "0 0 20px rgba(0, 212, 255, 0.3)",
      "0 0 0px rgba(0, 212, 255, 0)",
    ],
    transition: { duration: 0.4, ease: "easeOut" },
  },
};

/**
 * Hover depth variants: card lifts slightly with increased shadow on hover.
 * translateY -2px with 200ms ease transition.
 *
 * Validates: Requirements 14.5
 */
export const hoverDepthVariants: Variants = {
  rest: { y: 0, boxShadow: "0 0 0 rgba(0,0,0,0)" },
  hover: {
    y: -2,
    boxShadow: "0 4px 12px rgba(0, 0, 0, 0.3)",
    transition: { duration: 0.2, ease: "easeOut" },
  },
};

/**
 * New chart point entry animation: scale up from 0 with a spring.
 * Used for animating new data point arrivals on charts.
 *
 * Validates: Requirements 14.5
 */
export const chartPointEntry = {
  initial: { scale: 0, opacity: 0 },
  animate: { scale: 1, opacity: 1 },
  transition: { type: "spring" as const, stiffness: 300, damping: 20 },
};
