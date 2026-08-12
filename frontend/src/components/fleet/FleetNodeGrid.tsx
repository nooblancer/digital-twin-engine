"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { usePrefersReducedMotion } from "@/lib/animations";

interface FleetNodeGridProps {
  engines: Array<{ id: number; healthIndex: number; rul: number }>;
  onEngineSelect: (engineId: number) => void;
  onNodePositionsChange?: (positions: Map<number, { x: number; y: number }>) => void;
}

const BASE_SIZE = 40;
const MAX_SIZE = 80;
const MIN_RUL = 1;

/**
 * Determine the glow color class and hex based on engine health index.
 * - Emerald (#10b981) if health > 0.7
 * - Amber (#f59e0b) if 0.4 < health <= 0.7
 * - Crimson (#ef4444) if health <= 0.4
 */
function getHealthColor(healthIndex: number): {
  glowClass: string;
  pulseClass: string;
  hex: string;
  status: string;
} {
  if (healthIndex > 0.7) {
    return {
      glowClass: "glow-emerald",
      pulseClass: "glow-pulse-emerald",
      hex: "#10b981",
      status: "nominal",
    };
  }
  if (healthIndex > 0.4) {
    return {
      glowClass: "glow-amber",
      pulseClass: "glow-pulse-amber",
      hex: "#f59e0b",
      status: "degraded",
    };
  }
  return {
    glowClass: "glow-red",
    pulseClass: "glow-pulse-red",
    hex: "#ef4444",
    status: "critical",
  };
}

/**
 * Calculate node size proportional to urgency.
 * Size = baseSize + (maxSize - baseSize) * (1 / rul) normalized.
 * RUL is clamped to a minimum of 1 to avoid division by zero.
 */
function getNodeSize(rul: number): number {
  const clampedRul = Math.max(rul, MIN_RUL);
  const urgency = 1 / clampedRul;
  // Normalize: urgency ranges from ~0 (high RUL) to 1 (RUL=1)
  // We cap the normalized value at 1
  const normalizedUrgency = Math.min(urgency, 1);
  return BASE_SIZE + (MAX_SIZE - BASE_SIZE) * normalizedUrgency;
}

/**
 * FleetNodeGrid — displays each engine as a circular glowing node in a grid.
 * Nodes are sized by urgency (lower RUL = larger) and colored by health status.
 * Critical nodes pulse. Supports full keyboard navigation and ARIA labels.
 */
export function FleetNodeGrid({
  engines,
  onEngineSelect,
  onNodePositionsChange,
}: FleetNodeGridProps) {
  const prefersReducedMotion = usePrefersReducedMotion();
  const containerRef = React.useRef<HTMLDivElement>(null);
  const nodeRefs = React.useRef<Map<number, HTMLButtonElement>>(new Map());

  // Calculate and report node positions whenever engines change or container resizes
  const updatePositions = React.useCallback(() => {
    if (!onNodePositionsChange || !containerRef.current) return;

    const positions = new Map<number, { x: number; y: number }>();
    const containerRect = containerRef.current.getBoundingClientRect();

    nodeRefs.current.forEach((node, engineId) => {
      if (node) {
        const nodeRect = node.getBoundingClientRect();
        positions.set(engineId, {
          x: nodeRect.left - containerRect.left + nodeRect.width / 2,
          y: nodeRect.top - containerRect.top + nodeRect.height / 2,
        });
      }
    });

    onNodePositionsChange(positions);
  }, [onNodePositionsChange]);

  React.useEffect(() => {
    updatePositions();
  }, [engines, updatePositions]);

  // Update positions on resize
  React.useEffect(() => {
    if (!onNodePositionsChange) return;

    const observer = new ResizeObserver(() => {
      updatePositions();
    });

    if (containerRef.current) {
      observer.observe(containerRef.current);
    }

    return () => {
      observer.disconnect();
    };
  }, [onNodePositionsChange, updatePositions]);

  // Arrow key navigation for spatial movement
  const handleKeyDown = React.useCallback(
    (event: React.KeyboardEvent<HTMLButtonElement>, currentIndex: number) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onEngineSelect(engines[currentIndex].id);
        return;
      }

      let targetIndex: number | null = null;

      // Compute columns based on container width
      const container = containerRef.current;
      if (!container) return;

      const containerWidth = container.clientWidth;
      // Approximate columns based on node spacing (max node size + gap)
      const approxColWidth = MAX_SIZE + 24; // size + gap
      const cols = Math.max(1, Math.floor(containerWidth / approxColWidth));

      switch (event.key) {
        case "ArrowRight":
          targetIndex = currentIndex + 1 < engines.length ? currentIndex + 1 : null;
          break;
        case "ArrowLeft":
          targetIndex = currentIndex - 1 >= 0 ? currentIndex - 1 : null;
          break;
        case "ArrowDown":
          targetIndex =
            currentIndex + cols < engines.length ? currentIndex + cols : null;
          break;
        case "ArrowUp":
          targetIndex = currentIndex - cols >= 0 ? currentIndex - cols : null;
          break;
        default:
          return;
      }

      if (targetIndex !== null) {
        event.preventDefault();
        const targetEngine = engines[targetIndex];
        const targetNode = nodeRefs.current.get(targetEngine.id);
        if (targetNode) {
          targetNode.focus();
        }
      }
    },
    [engines, onEngineSelect]
  );

  const setNodeRef = React.useCallback(
    (engineId: number, el: HTMLButtonElement | null) => {
      if (el) {
        nodeRefs.current.set(engineId, el);
      } else {
        nodeRefs.current.delete(engineId);
      }
    },
    []
  );

  return (
    <div
      ref={containerRef}
      className="flex flex-wrap items-center justify-center gap-6 p-6"
      role="grid"
      aria-label="Fleet engine nodes"
    >
      {engines.map((engine, index) => {
        const size = getNodeSize(engine.rul);
        const { glowClass, pulseClass, hex, status } = getHealthColor(
          engine.healthIndex
        );
        const isCritical = engine.healthIndex <= 0.4;
        const shouldPulse = isCritical && !prefersReducedMotion;

        return (
          <button
            key={engine.id}
            ref={(el) => setNodeRef(engine.id, el)}
            type="button"
            role="gridcell"
            tabIndex={0}
            onClick={() => onEngineSelect(engine.id)}
            onKeyDown={(e) => handleKeyDown(e, index)}
            aria-label={`Engine ${engine.id}, health ${status}, RUL ${engine.rul} cycles`}
            className={cn(
              "rounded-full border border-white/10 transition-transform duration-200",
              "hover:scale-110 focus:outline-none focus:ring-2 focus:ring-cyan-400 focus:ring-offset-2 focus:ring-offset-[#0a0b0f]",
              "cursor-pointer flex items-center justify-center",
              glowClass,
              shouldPulse && pulseClass
            )}
            style={{
              width: `${size}px`,
              height: `${size}px`,
              backgroundColor: `${hex}20`,
              borderColor: `${hex}40`,
              ...(prefersReducedMotion
                ? { animation: "none" }
                : {}),
            }}
          >
            <span
              className="text-xs font-bold"
              style={{ color: hex }}
              aria-hidden="true"
            >
              {engine.id}
            </span>
          </button>
        );
      })}
    </div>
  );
}
