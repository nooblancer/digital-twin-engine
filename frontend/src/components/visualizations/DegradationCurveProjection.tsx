'use client';

import { useMemo, useId } from 'react';
import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from 'recharts';
import type { SimulationResult } from '@/types/simulation';

const CRITICAL_THRESHOLD = 0.4;

interface HistoricalPoint {
  cycle: number;
  healthIndex: number;
}

interface DegradationCurveProjectionProps {
  /** Historical health index trajectory data */
  historicalData: HistoricalPoint[];
  /** Projection percentiles from MonteCarloProjector, or null if not available */
  projectionPercentiles: SimulationResult['percentiles'] | null;
  /** Chart height in pixels */
  height?: number;
}

/**
 * Chart data point combining historical and projected values.
 * Historical points have `historical` set and projection fields null.
 * Projected points have `projected`, `projectedMedian`, and `confidenceBand` set.
 */
interface ChartDataPoint {
  cycle: number;
  /** Historical health index — solid line (null for projected region) */
  historical: number | null;
  /** Projected median (50th percentile) — gradient-faded line (null for historical region) */
  projected: number | null;
  /** 5th-95th confidence interval — shaded area (null for historical region) */
  confidenceBand: [number, number] | null;
}

/**
 * Custom tooltip for the degradation curve with projection.
 */
function DegradationTooltip({ active, payload }: any) {
  if (!active || !payload || payload.length === 0) return null;

  const data = payload[0]?.payload as ChartDataPoint | undefined;
  if (!data) return null;

  const isHistorical = data.historical !== null;

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
      {isHistorical ? (
        <p className="text-emerald-400">
          Health Index: {data.historical!.toFixed(4)}
        </p>
      ) : (
        <>
          <p className="text-emerald-400">
            Projected (Median): {data.projected?.toFixed(4) ?? '—'}
          </p>
          {data.confidenceBand && (
            <p className="text-cyan-400">
              90% CI: [{data.confidenceBand[0].toFixed(4)}, {data.confidenceBand[1].toFixed(4)}]
            </p>
          )}
        </>
      )}
    </div>
  );
}

/**
 * DegradationCurveProjection renders a combined historical + projected
 * health index degradation curve.
 *
 * - Historical: solid emerald line at full opacity
 * - Projection: gradient-faded emerald line (SVG linearGradient, emerald to transparent)
 * - Confidence interval: shaded cyan area (10% opacity) for 5th-95th percentile
 * - "Now" separator: vertical dashed line at the boundary
 * - Critical Threshold: horizontal dashed red line at y=0.4
 *
 * Uses Recharts ComposedChart combining Line and Area components.
 * Updates only the projection portion when simulation data changes
 * (historical data is memoized separately).
 */
export function DegradationCurveProjection({
  historicalData,
  projectionPercentiles,
  height = 300,
}: DegradationCurveProjectionProps) {
  const gradientId = useId();
  const safeGradientId = `projection-gradient-${gradientId.replace(/:/g, '')}`;

  // Memoize historical chart data separately so it doesn't re-compute
  // when only projection updates
  const historicalChartData: ChartDataPoint[] = useMemo(() => {
    return historicalData.map((point) => ({
      cycle: point.cycle,
      historical: point.healthIndex,
      projected: null,
      confidenceBand: null,
    }));
  }, [historicalData]);

  // Memoize projection chart data — updates when simulation changes
  const projectionChartData: ChartDataPoint[] = useMemo(() => {
    if (!projectionPercentiles) return [];

    const lastHistoricalCycle =
      historicalData.length > 0
        ? historicalData[historicalData.length - 1].cycle
        : 0;

    const numCycles = projectionPercentiles[50].length;
    const data: ChartDataPoint[] = [];

    for (let i = 0; i < numCycles; i++) {
      data.push({
        cycle: lastHistoricalCycle + i + 1,
        historical: null,
        projected: projectionPercentiles[50][i],
        confidenceBand: [projectionPercentiles[5][i], projectionPercentiles[95][i]],
      });
    }

    return data;
  }, [projectionPercentiles, historicalData]);

  // Combined data for the chart — historical then projection
  const chartData = useMemo(() => {
    // Add a bridge point: last historical point also appears as first projection
    // so the lines connect visually
    if (historicalChartData.length > 0 && projectionChartData.length > 0) {
      const lastHistorical = historicalChartData[historicalChartData.length - 1];
      const bridgePoint: ChartDataPoint = {
        cycle: lastHistorical.cycle,
        historical: lastHistorical.historical,
        projected: lastHistorical.historical, // connect line at this point
        confidenceBand: lastHistorical.historical !== null
          ? [lastHistorical.historical, lastHistorical.historical]
          : null,
      };
      return [
        ...historicalChartData.slice(0, -1),
        bridgePoint,
        ...projectionChartData,
      ];
    }
    return [...historicalChartData, ...projectionChartData];
  }, [historicalChartData, projectionChartData]);

  // The "Now" line position — last historical cycle
  const nowCycle = useMemo(() => {
    if (historicalData.length === 0) return null;
    return historicalData[historicalData.length - 1].cycle;
  }, [historicalData]);

  if (historicalData.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-white/5 bg-[#12141a]"
        style={{ height }}
      >
        <p className="text-sm text-gray-400">
          No trajectory data available yet. Waiting for health updates...
        </p>
      </div>
    );
  }

  return (
    <div className="w-full">
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={chartData} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
          {/* SVG defs for projection gradient */}
          <defs>
            <linearGradient id={safeGradientId} x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#10b981" stopOpacity={1} />
              <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
            </linearGradient>
          </defs>

          <CartesianGrid stroke="hsl(220, 10%, 20%)" strokeDasharray="3 3" />

          <XAxis
            dataKey="cycle"
            label={{
              value: 'Cycle',
              position: 'insideBottom',
              offset: -4,
              style: { fill: 'hsl(215, 12%, 58%)', fontSize: 11 },
            }}
            stroke="hsl(215, 12%, 58%)"
            tick={{ fontSize: 11 }}
          />

          <YAxis
            domain={[0, 1]}
            label={{
              value: 'Health Index',
              angle: -90,
              position: 'insideLeft',
              offset: 10,
              style: { fill: 'hsl(215, 12%, 58%)', fontSize: 11 },
            }}
            stroke="hsl(215, 12%, 58%)"
            tick={{ fontSize: 11 }}
          />

          <Tooltip content={<DegradationTooltip />} />

          {/* Critical Threshold — horizontal dashed red line at 0.4 */}
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

          {/* "Now" separator — vertical dashed line at boundary */}
          {nowCycle !== null && projectionPercentiles !== null && (
            <ReferenceLine
              x={nowCycle}
              stroke="hsl(215, 12%, 58%)"
              strokeDasharray="4 4"
              strokeWidth={1}
              label={{
                value: 'Now',
                position: 'top',
                fill: 'hsl(215, 12%, 58%)',
                fontSize: 11,
              }}
            />
          )}

          {/* 5th-95th confidence interval — shaded cyan area (10% opacity) */}
          <Area
            type="monotone"
            dataKey="confidenceBand"
            name="90% Confidence Interval"
            stroke="none"
            fill="#00d4ff"
            fillOpacity={0.1}
            isAnimationActive={true}
            animationDuration={500}
            connectNulls={false}
          />

          {/* Historical health index — solid emerald line (full opacity) */}
          <Line
            type="monotone"
            dataKey="historical"
            name="Historical Health Index"
            stroke="#10b981"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
            connectNulls={false}
          />

          {/* Future projection — gradient-faded emerald line */}
          <Line
            type="monotone"
            dataKey="projected"
            name="Projected Health Index"
            stroke={`url(#${safeGradientId})`}
            strokeWidth={2}
            dot={false}
            isAnimationActive={true}
            animationDuration={500}
            connectNulls={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
