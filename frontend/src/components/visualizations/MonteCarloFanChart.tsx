'use client';

import { useMemo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from 'recharts';
import type { SimulationResult } from '@/types/simulation';

const CRITICAL_THRESHOLD = 0.4;

interface MonteCarloFanChartProps {
  /** Percentiles from SimulationResult, or null when no data is available */
  percentiles: SimulationResult['percentiles'] | null;
  /** Chart height in pixels */
  height?: number;
}

export interface FanDataPoint {
  cycle: number;
  /** Band from 5th to 95th percentile — rendered as [low, high] */
  band95: [number, number];
  /** Band from 25th to 75th percentile — rendered as [low, high] */
  band75: [number, number];
  /** Median (50th percentile) line value */
  median: number;
  /** Individual percentile values for tooltip */
  p5: number;
  p25: number;
  p50: number;
  p75: number;
  p95: number;
}

/**
 * Transform raw percentile arrays from the simulation API into chart-ready data points.
 * Each input percentile array (keyed by 5, 25, 50, 75, 95) has the same length (horizon_cycles).
 * Output is one FanDataPoint per cycle with all percentile values at correct positions.
 */
export function transformPercentiles(percentiles: SimulationResult['percentiles']): FanDataPoint[] {
  const numCycles = percentiles[50].length;
  const data: FanDataPoint[] = [];

  for (let i = 0; i < numCycles; i++) {
    data.push({
      cycle: i + 1,
      band95: [percentiles[5][i], percentiles[95][i]],
      band75: [percentiles[25][i], percentiles[75][i]],
      median: percentiles[50][i],
      p5: percentiles[5][i],
      p25: percentiles[25][i],
      p50: percentiles[50][i],
      p75: percentiles[75][i],
      p95: percentiles[95][i],
    });
  }

  return data;
}

/**
 * Custom tooltip displaying all percentile values at the hovered cycle.
 */
function FanChartTooltip({ active, payload, label }: any) {
  if (!active || !payload || payload.length === 0) return null;

  // Extract percentile values from the first payload entry's raw data
  const data = payload[0]?.payload as FanDataPoint | undefined;
  if (!data) return null;

  return (
    <div
      className="rounded-md border px-3 py-2 text-xs"
      style={{
        backgroundColor: 'hsl(220, 13%, 9%)',
        border: '1px solid hsl(220, 12%, 18%)',
        color: 'hsl(210, 20%, 92%)',
      }}
    >
      <p className="mb-1 font-medium">Cycle {data.cycle}</p>
      <p className="text-red-400">P95: {data.p95.toFixed(3)}</p>
      <p className="text-orange-300">P75: {data.p75.toFixed(3)}</p>
      <p className="text-emerald-400 font-semibold">P50 (Median): {data.p50.toFixed(3)}</p>
      <p className="text-orange-300">P25: {data.p25.toFixed(3)}</p>
      <p className="text-red-400">P5: {data.p5.toFixed(3)}</p>
    </div>
  );
}

/**
 * MonteCarloFanChart renders a fan-shaped area chart visualizing
 * Monte Carlo forward projection percentiles for engine health index.
 *
 * Bands:
 *  - 5th–95th percentile: very faint fill (opacity 0.08)
 *  - 25th–75th percentile: moderate fill (opacity 0.2)
 *  - 50th percentile (median): solid emerald line
 *
 * Also renders a horizontal dashed red Critical Threshold line at 0.4.
 */
export function MonteCarloFanChart({ percentiles, height = 300 }: MonteCarloFanChartProps) {
  const chartData: FanDataPoint[] = useMemo(() => {
    if (!percentiles) return [];
    return transformPercentiles(percentiles);
  }, [percentiles]);

  if (!percentiles) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-white/5 bg-[#12141a]"
        style={{ height }}
      >
        <p className="text-sm text-gray-400">
          No simulation data available. Adjust the stress slider to generate a projection.
        </p>
      </div>
    );
  }

  return (
    <div className="w-full">
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={chartData} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
          <CartesianGrid stroke="hsl(220, 10%, 20%)" strokeDasharray="3 3" />

          <XAxis
            dataKey="cycle"
            label={{ value: 'Cycles from Now', position: 'insideBottom', offset: -4, style: { fill: 'hsl(215, 12%, 58%)', fontSize: 11 } }}
            stroke="hsl(215, 12%, 58%)"
            tick={{ fontSize: 11 }}
          />

          <YAxis
            domain={[0, 1]}
            label={{ value: 'Health Index', angle: -90, position: 'insideLeft', offset: 10, style: { fill: 'hsl(215, 12%, 58%)', fontSize: 11 } }}
            stroke="hsl(215, 12%, 58%)"
            tick={{ fontSize: 11 }}
          />

          <Tooltip content={<FanChartTooltip />} />

          {/* Critical Threshold reference line */}
          <ReferenceLine
            y={CRITICAL_THRESHOLD}
            stroke="#ef4444"
            strokeDasharray="6 4"
            strokeWidth={1.5}
            label={{
              value: 'Critical Threshold',
              position: 'right',
              fill: '#ef4444',
              fontSize: 11,
            }}
          />

          {/* 5th–95th percentile band — widest, faintest */}
          <Area
            type="monotone"
            dataKey="band95"
            name="5th–95th Percentile"
            stroke="none"
            fill="#00d4ff"
            fillOpacity={0.08}
            animationDuration={500}
            isAnimationActive={true}
          />

          {/* 25th–75th percentile band — moderate opacity */}
          <Area
            type="monotone"
            dataKey="band75"
            name="25th–75th Percentile"
            stroke="none"
            fill="#00d4ff"
            fillOpacity={0.2}
            animationDuration={500}
            isAnimationActive={true}
          />

          {/* Median line (50th percentile) — solid emerald */}
          <Area
            type="monotone"
            dataKey="median"
            name="Median (50th)"
            stroke="#10b981"
            strokeWidth={2}
            fill="none"
            animationDuration={500}
            isAnimationActive={true}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
