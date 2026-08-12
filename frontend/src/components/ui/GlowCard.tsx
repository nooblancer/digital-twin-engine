"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

type GlowColor = "cyan" | "violet" | "emerald" | "red" | "amber" | "none";

interface GlowCardProps {
  children: React.ReactNode;
  glowColor?: GlowColor;
  isActive?: boolean;
  className?: string;
}

const glowStaticClass: Record<GlowColor, string> = {
  cyan: "glow-cyan",
  violet: "glow-violet",
  emerald: "glow-emerald",
  red: "glow-red",
  amber: "glow-amber",
  none: "",
};

const glowPulseClass: Record<GlowColor, string> = {
  cyan: "glow-pulse-cyan",
  violet: "glow-pulse-violet",
  emerald: "glow-pulse-emerald",
  red: "glow-pulse-red",
  amber: "glow-pulse-amber",
  none: "",
};

/**
 * GlowCard — a card component with colored glow effects.
 *
 * Renders a surface-1 card with optional persistent glow and a pulse
 * animation triggered on false→true transitions of `isActive`.
 */
export function GlowCard({
  children,
  glowColor = "cyan",
  isActive = false,
  className,
}: GlowCardProps) {
  const [isPulsing, setIsPulsing] = React.useState(false);
  const prevActiveRef = React.useRef(isActive);

  React.useEffect(() => {
    // Detect false→true transition
    if (isActive && !prevActiveRef.current) {
      setIsPulsing(true);

      // Remove the pulse class after animation duration (400ms)
      const timer = setTimeout(() => {
        setIsPulsing(false);
      }, 400);

      prevActiveRef.current = isActive;
      return () => clearTimeout(timer);
    }

    prevActiveRef.current = isActive;
  }, [isActive]);

  return (
    <div
      className={cn(
        "bg-mission-surface-1 rounded-md border border-white/[0.06]",
        isActive && glowColor !== "none" && glowStaticClass[glowColor],
        isPulsing && glowColor !== "none" && glowPulseClass[glowColor],
        className
      )}
    >
      {children}
    </div>
  );
}
