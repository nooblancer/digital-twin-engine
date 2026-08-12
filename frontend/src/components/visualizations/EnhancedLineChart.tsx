'use client';

import { useMemo } from 'react';
import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import type { ActiveDotProps } from 'recharts';
import { cn } from '@/lib/utils';

/**
 * EnhancedLineChart — Recharts wrapper with gradient fills, glow dots,
 * and a glass-styled custom tooltip.
 *
 * Validates: Requirements 9.1, 9.2, 9.4, 9.5
 */

// --- Types ---

export interface SeriesConfig {
  dataKey: string;
  color: string; // hex color for line and gradient
  name: string;
}

export interface EnhancedLineChartProps {
  data: Array<Record<string, number | string>>;
  series: SeriesConfig[];
  xAxisKey?: string;
  height?: number;
  showGlowDot?: boolean;
  gradientFill?: boolean;
  className?: string;
}

// --- Performance constants ---

const MAX_VISIBLE_POINTS = 200;
const ANIMATION_THRESHOLD = 150;

// --- Helpers ---

function formatTimestamp(value: number | string): string {
  const ts = typeof value === 'string' ? Number(value) : value;
  if (Number.isNaN(ts)) return String(value);
  const now = Date.now();
  const secondsAgo = Math.round((now - ts) / 1000);
  if (secondsAgo <= 0) return 'now';
  if (secondsAgo < 60) return `${secondsAgo}s ago`;
  const minutesAgo = Math.round(secondsAgo / 60);
  return `${minutesAgo}m ago`;
}

// --- GlowDot: custom active dot rendering ---

/**
 * Creates an activeDot render function for a given series.
 * Renders a standard small dot for all points except the last one,
 * which gets a larger circle with a radial glow effect.
 *
 * Requirement 9.2 — glow effect on most recent data point.
 */
function makeGlowDot(color: string, dataLength: number) {
  return function GlowDotRenderer(props: ActiveDotProps) {
    const { cx, cy, index } = props;
    if (cx == null || cy == null || index == null) return null;

    const isLast = index === dataLength - 1;

    if (!isLast) {
      return null; // Don't render dots for non-last points (performance)
    }

    return (
      <g>
        {/* Radial glow — larger semi-transparent circle */}
        <circle cx={cx} cy={cy} r={8} fill={color} opacity={0.2} />
        {/* Core dot */}
        <circle cx={cx} cy={cy} r={5} fill={color} />
      </g>
    );
  };
}

// --- Custom Tooltip ---

interface CustomTooltipPayloadEntry {
  name: string;
  value: number;
  dataKey: string;
  color: string;
  payload: Record<string, number | string>;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: CustomTooltipPayloadEntry[];
  label?: number | string;
  seriesNames: Map<string, string>;
}

/**
 * Glass-styled tooltip showing sensor name, value, timestamp, and deviation.
 *
 * Requirement 9.4 — custom tooltip with detailed breakdown.
 */
function ChartTooltip({ active, payload, label, seriesNames }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;

  const timestamp = typeof label === 'number' ? formatTimestamp(label) : String(label ?? '');

  return (
    <div
      className="glass rounded-md px-3 py-2 text-sm shadow-lg border border-white/[0.06]"
      style={{ minWidth: 160 }}
    >
      <p className="text-[#a0aec0] text-xs mb-1">{timestamp}</p>
      {payload.map((entry) => {
        const sensorName = seriesNames.get(entry.dataKey) ?? entry.name;
        // Compute deviation from baseline (first point value for this key)
        const baselineValue = entry.payload[`${entry.dataKey}_baseline`] as number | undefined;
        const deviation =
          baselineValue != null ? entry.value - baselineValue : undefined;

        return (
          <div key={entry.dataKey} className="flex flex-col gap-0.5 mb-1 last:mb-0">
            <div className="flex items-center gap-2">
              <span
                className="inline-block w-2 h-2 rounded-full"
                style={{ backgroundColor: entry.color }}
              />
              <span className="text-[#e2e8f0] font-medium">{sensorName}</span>
            </div>
            <div className="ml-4 text-xs text-[#a0aec0]">
              <span>Value: {typeof entry.value === 'number' ? entry.value.toFixed(2) : entry.value}</span>
              {deviation != null && (
                <span className="ml-2">
                  Δ {deviation >= 0 ? '+' : ''}{deviation.toFixed(2)}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// --- Main Component ---

export function EnhancedLineChart({
  data,
  series,
  xAxisKey = 'timestamp',
  height = 250,
  showGlowDot = true,
  gradientFill = true,
  className,
}: EnhancedLineChartProps) {
  // Performance: limit visible data points to MAX_VISIBLE_POINTS (Requirement 9.5)
  const visibleData = useMemo(() => {
    if (data.length <= MAX_VISIBLE_POINTS) return data;
    return data.slice(data.length - MAX_VISIBLE_POINTS);
  }, [data]);

  // Disable animation for large datasets (> 150 points) for 60fps performance
  const shouldAnimate = visibleData.length <= ANIMATION_THRESHOLD;

  // Build a series name lookup map for the tooltip
  const seriesNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const s of series) {
      map.set(s.dataKey, s.name);
    }
    return map;
  }, [series]);

  // Generate stable gradient IDs to avoid conflicts with multiple charts on page
  const gradientIds = useMemo(() => {
    return series.map((s) => `enhanced-gradient-${s.dataKey}-${s.color.replace('#', '')}`);
  }, [series]);

  return (
    <div className={cn('w-full', className)}>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={visibleData} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
          {/* Gradient definitions — Requirement 9.1 */}
          <defs>
            {gradientFill &&
              series.map((s, i) => (
                <linearGradient
                  key={gradientIds[i]}
                  id={gradientIds[i]}
                  x1="0"
                  y1="0"
                  x2="0"
                  y2="1"
                >
                  <stop offset="0%" stopColor={s.color} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={s.color} stopOpacity={0} />
                </linearGradient>
              ))}
          </defs>

          <CartesianGrid stroke="hsl(220, 10%, 20%)" strokeDasharray="3 3" />

          <XAxis
            dataKey={xAxisKey}
            tickFormatter={(value) => formatTimestamp(value)}
            stroke="hsl(215, 12%, 58%)"
            tick={{ fontSize: 11 }}
          />
          <YAxis stroke="hsl(215, 12%, 58%)" tick={{ fontSize: 11 }} />

          {/* Custom glass tooltip — Requirement 9.4 */}
          <Tooltip
            content={<ChartTooltip seriesNames={seriesNames} />}
            cursor={{ stroke: 'rgba(255,255,255,0.1)', strokeWidth: 1 }}
          />

          {/* Gradient fill areas — Requirement 9.1 */}
          {gradientFill &&
            series.map((s, i) => (
              <Area
                key={`area-${s.dataKey}`}
                type="monotone"
                dataKey={s.dataKey}
                stroke="none"
                fill={`url(#${gradientIds[i]})`}
                fillOpacity={1}
                isAnimationActive={shouldAnimate}
              />
            ))}

          {/* Line series with optional glow dot — Requirements 9.1, 9.2 */}
          {series.map((s) => (
            <Line
              key={`line-${s.dataKey}`}
              type="monotone"
              dataKey={s.dataKey}
              name={s.name}
              stroke={s.color}
              strokeWidth={2}
              dot={false}
              activeDot={
                showGlowDot
                  ? makeGlowDot(s.color, visibleData.length)
                  : undefined
              }
              isAnimationActive={shouldAnimate}
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
