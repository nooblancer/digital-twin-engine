"use client";

import * as React from "react";
import { useSpring, useTransform, motion, useMotionValue } from "framer-motion";
import { cn } from "@/lib/utils";
import { usePrefersReducedMotion, counterSpring } from "@/lib/animations";

interface AnimatedCounterProps {
  /** The numeric value to display */
  value: number;
  /** Label displayed below or beside the number */
  label?: string;
  /** Formatting function applied to the displayed number (e.g., toFixed, toLocaleString) */
  format?: (value: number) => string;
  /** Additional CSS classes */
  className?: string;
}

/**
 * AnimatedCounter — animates numeric value transitions using spring physics.
 *
 * Uses framer-motion useSpring + useTransform for smooth number interpolation.
 * Respects prefers-reduced-motion: instantly updates without animation when
 * the user has indicated a preference for reduced motion.
 *
 * Validates: Requirements 14.2
 */
export function AnimatedCounter({
  value,
  label,
  format = (v) => Math.round(v).toLocaleString(),
  className,
}: AnimatedCounterProps) {
  const prefersReducedMotion = usePrefersReducedMotion();

  // Motion value that drives the spring animation
  const motionValue = useMotionValue(value);

  // Spring-animated version of the motion value
  const springValue = useSpring(motionValue, {
    stiffness: counterSpring.stiffness,
    damping: counterSpring.damping,
    mass: counterSpring.mass,
  });

  // Transform the spring output into a formatted string
  const display = useTransform(springValue, (latest) => format(latest));

  // Track the displayed text via React state for rendering
  const [displayText, setDisplayText] = React.useState(() => format(value));

  // When the value prop changes, update the motion value target
  React.useEffect(() => {
    if (prefersReducedMotion) {
      // Skip animation — set immediately
      motionValue.set(value);
      setDisplayText(format(value));
    } else {
      motionValue.set(value);
    }
  }, [value, prefersReducedMotion, motionValue, format]);

  // Subscribe to the display transform to update rendered text
  React.useEffect(() => {
    if (prefersReducedMotion) {
      return;
    }

    const unsubscribe = display.on("change", (latest) => {
      setDisplayText(latest);
    });

    return unsubscribe;
  }, [display, prefersReducedMotion]);

  return (
    <div className={cn("flex flex-col items-center", className)}>
      <motion.span
        className="text-2xl font-semibold tabular-nums text-mission-cyan"
        aria-live="polite"
        aria-atomic="true"
      >
        {displayText}
      </motion.span>
      {label && (
        <span className="text-xs text-white/60 mt-0.5">{label}</span>
      )}
    </div>
  );
}
