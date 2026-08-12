"use client";

import { cn } from "@/lib/utils";

type PulseStatus = "connected" | "disconnected" | "connecting";

interface PulseIndicatorProps {
  status: PulseStatus;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const sizeMap = {
  sm: 8,
  md: 12,
  lg: 16,
} as const;

/**
 * PulseIndicator — A circular indicator showing live WebSocket connection status.
 *
 * - Connected: green (#10b981) with CSS scale/fade pulse animation
 * - Disconnected: red (#ef4444), static (no animation)
 * - Connecting: amber (#f59e0b), opacity blink animation
 *
 * Respects prefers-reduced-motion by disabling animations via CSS media query.
 */
export function PulseIndicator({
  status,
  size = "md",
  className,
}: PulseIndicatorProps) {
  const diameter = sizeMap[size];

  return (
    <span
      role="status"
      aria-label={`Connection ${status}`}
      className={cn(
        "relative inline-flex shrink-0 rounded-full",
        status === "connected" && "bg-[#10b981] pulse-indicator-connected",
        status === "disconnected" && "bg-[#ef4444]",
        status === "connecting" && "bg-[#f59e0b] pulse-indicator-connecting",
        className
      )}
      style={{ width: diameter, height: diameter }}
    />
  );
}
