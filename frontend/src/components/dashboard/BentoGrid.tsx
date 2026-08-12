"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

export type CardSize = "1x1" | "2x1" | "1x2" | "2x2" | "3x2";

export interface BentoGridItem {
  id: string;
  size: CardSize;
  component: React.ReactNode;
}

export interface BentoGridProps {
  items: BentoGridItem[];
  className?: string;
}

/**
 * Maps CardSize to CSS Grid column/row span classes.
 *
 * Format: "CxR" where C = columns spanned, R = rows spanned.
 */
const sizeToSpanClass: Record<CardSize, string> = {
  "1x1": "bento-1x1",
  "2x1": "bento-2x1",
  "1x2": "bento-1x2",
  "2x2": "bento-2x2",
  "3x2": "bento-3x2",
};

/**
 * BentoGrid — A dense CSS Grid layout with variable card sizes for the
 * Mission Control dashboard.
 *
 * Uses a 4-column grid with 200px auto rows and 16px gap. Items are placed
 * using column/row spans determined by their `size` prop. Collapses to a
 * single-column layout on viewports narrower than 768px.
 *
 * Each item is rendered inside a stable slot that does not shift when
 * child content updates (overflow hidden + contain: layout).
 */
export function BentoGrid({ items, className }: BentoGridProps) {
  return (
    <div className={cn("bento-grid", className)}>
      {items.map((item) => (
        <BentoGridSlot key={item.id} size={item.size}>
          {item.component}
        </BentoGridSlot>
      ))}
    </div>
  );
}

interface BentoGridSlotProps {
  size: CardSize;
  children: React.ReactNode;
}

/**
 * BentoGridSlot — Individual grid cell that contains a card component.
 *
 * Prevents layout shifts by using overflow-hidden and CSS containment so
 * that child content changes (e.g. from WebSocket updates) do not cause
 * the grid to reflow.
 */
function BentoGridSlot({ size, children }: BentoGridSlotProps) {
  return (
    <div
      className={cn(
        sizeToSpanClass[size],
        "min-w-0 min-h-0 overflow-hidden"
      )}
      style={{ contain: "layout" }}
    >
      {children}
    </div>
  );
}
