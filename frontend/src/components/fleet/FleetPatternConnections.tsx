"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { usePrefersReducedMotion } from "@/lib/animations";
import type { FleetPatternResponse, EnginePairSimilarity } from "@/types/fleet";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FleetPatternConnectionsProps {
  nodePositions: Map<number, { x: number; y: number }>;
  pollingIntervalMs?: number; // default 60000
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const DEFAULT_POLL_INTERVAL = 60000;

/** Accent-secondary violet used for connection lines */
const CONNECTION_COLOR = "#7c3aed";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Line thickness proportional to similarity score.
 * 1px at 0.7 similarity, 4px at 1.0 similarity.
 * Formula: 1 + 10 * (similarity - 0.7)
 */
function getStrokeWidth(similarity: number): number {
  return 1 + 10 * (similarity - 0.7);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function FleetPatternConnections({
  nodePositions,
  pollingIntervalMs = DEFAULT_POLL_INTERVAL,
}: FleetPatternConnectionsProps) {
  const [patterns, setPatterns] = useState<FleetPatternResponse | null>(null);
  const prefersReducedMotion = usePrefersReducedMotion();
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // -------------------------------------------------------------------------
  // Data fetching
  // -------------------------------------------------------------------------

  const fetchPatterns = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/fleet/patterns`);
      if (!response.ok) return;
      const data: FleetPatternResponse = await response.json();
      setPatterns(data);
    } catch {
      // Silently handle network errors — connections will simply not render
    }
  }, []);

  useEffect(() => {
    fetchPatterns();

    intervalRef.current = setInterval(fetchPatterns, pollingIntervalMs);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [fetchPatterns, pollingIntervalMs]);

  // -------------------------------------------------------------------------
  // Build connection lines from pattern data
  // -------------------------------------------------------------------------

  const connections: Array<{
    key: string;
    x1: number;
    y1: number;
    x2: number;
    y2: number;
    similarity: number;
  }> = [];

  if (patterns && patterns.clusters.length > 0) {
    patterns.clusters.forEach((cluster) => {
      cluster.pairwise_similarities.forEach((pair: EnginePairSimilarity) => {
        const posA = nodePositions.get(pair.engine_a);
        const posB = nodePositions.get(pair.engine_b);

        if (posA && posB) {
          connections.push({
            key: `${pair.engine_a}-${pair.engine_b}`,
            x1: posA.x,
            y1: posA.y,
            x2: posB.x,
            y2: posB.y,
            similarity: pair.similarity_score,
          });
        }
      });
    });
  }

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  if (connections.length === 0) {
    return null;
  }

  return (
    <svg
      className="absolute inset-0 w-full h-full pointer-events-none"
      data-testid="fleet-pattern-connections"
      aria-hidden="true"
    >
      {!prefersReducedMotion && (
        <defs>
          <style>
            {`
              @keyframes dashFlow {
                from { stroke-dashoffset: 20; }
                to { stroke-dashoffset: 0; }
              }
            `}
          </style>
        </defs>
      )}

      {connections.map((conn) => (
        <line
          key={conn.key}
          x1={conn.x1}
          y1={conn.y1}
          x2={conn.x2}
          y2={conn.y2}
          stroke={CONNECTION_COLOR}
          strokeWidth={getStrokeWidth(conn.similarity)}
          strokeOpacity={conn.similarity}
          strokeDasharray={prefersReducedMotion ? "none" : "6 4"}
          strokeLinecap="round"
          style={{
            transition:
              "stroke-width 0.4s ease, stroke-opacity 0.4s ease, x1 0.4s ease, y1 0.4s ease, x2 0.4s ease, y2 0.4s ease",
            animation: prefersReducedMotion
              ? "none"
              : "dashFlow 1.5s linear infinite",
          }}
        />
      ))}
    </svg>
  );
}
