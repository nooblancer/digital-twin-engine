'use client';

import { motion } from 'framer-motion';
import { useStore } from '@/store';

interface InnovationMeterProps {
  /** Sensor ID to display innovation magnitude for */
  sensorId: string;
  /** Maximum threshold for normalization (default: 5.0) */
  maxThreshold?: number;
}

/**
 * Returns the bar color based on the normalized fill percentage.
 * Green (<33%): minimal correction needed
 * Amber (33–66%): moderate correction
 * Red (>66%): large correction / significant deviation
 */
export function getBarColor(normalizedValue: number): string {
  if (normalizedValue < 0.33) return '#10b981'; // green (emerald-500)
  if (normalizedValue < 0.66) return '#f59e0b'; // amber (amber-500)
  return '#ef4444'; // red (red-500)
}

/**
 * Computes the normalized bar width as a percentage (0–100),
 * clamped so it never exceeds 100%.
 */
export function getBarWidth(magnitude: number | null, maxThreshold: number): number {
  if (magnitude === null || magnitude <= 0) return 0;
  return Math.min(magnitude / maxThreshold, 1.0) * 100;
}

/**
 * InnovationMeter — Visual gauge showing innovation magnitude.
 *
 * Displays a horizontal bar whose fill is proportional to
 * innovation_magnitude / maxThreshold (clamped to 1.0).
 * Color gradient: green (<33%), amber (33–66%), red (>66%).
 * Animates bar width transitions with Framer Motion.
 *
 * Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
 */
export function InnovationMeter({ sensorId, maxThreshold = 5.0 }: InnovationMeterProps) {
  const innovationMagnitude = useStore(
    (state) => state.latestInnovation[sensorId] ?? null
  );

  const normalizedValue = innovationMagnitude !== null
    ? Math.min(innovationMagnitude / maxThreshold, 1.0)
    : 0;

  const barWidthPercent = getBarWidth(innovationMagnitude, maxThreshold);
  const barColor = getBarColor(normalizedValue);

  return (
    <div className="w-full">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs font-medium text-muted-foreground">
          Innovation Magnitude
        </span>
        <span
          className="text-xs font-semibold tabular-nums"
          style={{ color: barColor }}
        >
          {innovationMagnitude !== null
            ? innovationMagnitude.toFixed(3)
            : '—'}
        </span>
      </div>

      {/* Outer track */}
      <div
        className="relative h-5 w-full rounded overflow-hidden"
        style={{ backgroundColor: 'hsl(220, 13%, 12%)' }}
        role="meter"
        aria-valuenow={innovationMagnitude ?? 0}
        aria-valuemin={0}
        aria-valuemax={maxThreshold}
        aria-label={`Innovation magnitude: ${innovationMagnitude !== null ? innovationMagnitude.toFixed(3) : 'no data'}`}
      >
        {/* Animated fill bar */}
        <motion.div
          className="absolute inset-y-0 left-0 rounded"
          animate={{
            width: `${barWidthPercent}%`,
            backgroundColor: barColor,
          }}
          transition={{
            width: { type: 'spring', stiffness: 120, damping: 20 },
            backgroundColor: { duration: 0.3 },
          }}
          style={{ minWidth: barWidthPercent > 0 ? '2px' : '0px' }}
        />
      </div>

      {/* Scale markers */}
      <div className="flex justify-between mt-1">
        <span className="text-[10px] text-muted-foreground">0</span>
        <span className="text-[10px] text-muted-foreground">
          {maxThreshold.toFixed(1)}
        </span>
      </div>
    </div>
  );
}
