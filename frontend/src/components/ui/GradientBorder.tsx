"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

interface GradientBorderProps {
  children: React.ReactNode;
  /** CSS gradient string, default: "linear-gradient(135deg, #00d4ff, #7c3aed, #10b981)" */
  gradient?: string;
  /** Border width in pixels, default: 1 */
  borderWidth?: number;
  /** Whether gradient rotation animation is active, default: true */
  animated?: boolean;
  className?: string;
}

/**
 * GradientBorder renders an animated gradient border around its children.
 *
 * Uses a padding-based approach: an outer wrapper displays the gradient as its
 * background, with padding equal to `borderWidth`. The inner content div sits
 * on top, creating the border illusion. When `animated` is true, the gradient
 * rotates via CSS keyframe animation.
 *
 * Respects `prefers-reduced-motion` — rotation stops when the user prefers
 * reduced motion.
 */
export function GradientBorder({
  children,
  gradient = "linear-gradient(135deg, #00d4ff, #7c3aed, #10b981)",
  borderWidth = 1,
  animated = true,
  className,
}: GradientBorderProps) {
  return (
    <div
      className={cn(
        "gradient-border-wrapper relative rounded-md",
        animated && "gradient-border-animated",
        className
      )}
      style={{
        padding: `${borderWidth}px`,
      }}
      aria-hidden="true"
    >
      {/* Gradient background layer */}
      <div
        className="gradient-border-bg absolute inset-0 rounded-[inherit]"
        style={{
          background: gradient,
          backgroundSize: "200% 200%",
        }}
      />
      {/* Content layer */}
      <div className="gradient-border-content relative rounded-[inherit] bg-mission-surface-1">
        {children}
      </div>
    </div>
  );
}
