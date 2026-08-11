'use client';

import { motion, AnimatePresence } from 'framer-motion';

interface RULCountdownProps {
  /** Expected RUL in cycles (median from Monte Carlo), or null if no data */
  expectedRul: number | null;
  /** 90% confidence interval [low, high] from Monte Carlo, or null if no data */
  confidenceInterval90: [number, number] | null;
}

/**
 * Determine the color class based on RUL value.
 * - RUL < 20 → red (critical)
 * - 20-40 → amber (warning)
 * - > 40 → emerald (nominal)
 */
export function getRulColorClass(rul: number): string {
  if (rul < 20) return 'text-red-500';
  if (rul <= 40) return 'text-amber-500';
  return 'text-emerald-500';
}

/**
 * Determine the border glow class based on RUL value.
 * - RUL < 20 → red pulse border
 * - 20-40 → amber glow border
 * - > 40 → default subtle border
 */
function getBorderClass(rul: number): string {
  if (rul < 20) return 'border-red-500/50 shadow-[0_0_15px_rgba(239,68,68,0.3)]';
  if (rul <= 40) return 'border-amber-500/30 shadow-[0_0_12px_rgba(245,158,11,0.2)]';
  return 'border-white/[0.06]';
}

/**
 * Compute the ± range from the confidence interval relative to the median.
 * Returns the maximum deviation from the median.
 */
function computeMargin(expectedRul: number, ci: [number, number]): number {
  const low = ci[0];
  const high = ci[1];
  return Math.max(Math.abs(expectedRul - low), Math.abs(high - expectedRul));
}

/**
 * RULCountdown — Animated remaining useful life display with Monte Carlo
 * confidence range. Shows a large countdown number with color-coded urgency
 * and pulsing animation when critical.
 *
 * Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7
 */
export function RULCountdown({ expectedRul, confidenceInterval90 }: RULCountdownProps) {
  // Null state — no simulation data available
  if (expectedRul === null) {
    return (
      <div className="rounded-lg border border-white/[0.06] bg-[#12141a] p-6 text-center">
        <p className="text-sm uppercase tracking-wider text-[hsl(215,12%,58%)] mb-2">
          Remaining Useful Life
        </p>
        <p className="text-6xl font-mono font-bold text-[hsl(215,12%,58%)]">
          --
        </p>
        <p className="mt-2 text-sm text-[hsl(215,12%,58%)]">
          Awaiting data
        </p>
      </div>
    );
  }

  const colorClass = getRulColorClass(expectedRul);
  const borderClass = getBorderClass(expectedRul);
  const isCritical = expectedRul < 20;
  const margin = confidenceInterval90
    ? computeMargin(expectedRul, confidenceInterval90)
    : null;

  return (
    <div
      className={`rounded-lg border bg-[#12141a] p-6 text-center transition-shadow duration-300 ${borderClass}`}
    >
      <p className="text-sm uppercase tracking-wider text-[hsl(215,12%,58%)] mb-2">
        Remaining Useful Life
      </p>

      {/* Animated RUL number */}
      <AnimatePresence mode="wait">
        <motion.p
          key={expectedRul}
          className={`text-6xl font-mono font-bold ${colorClass}`}
          initial={{ opacity: 0, scale: 0.8 }}
          animate={
            isCritical
              ? {
                  opacity: 1,
                  scale: [1, 1.05, 1],
                }
              : { opacity: 1, scale: 1 }
          }
          exit={{ opacity: 0, scale: 0.8 }}
          transition={
            isCritical
              ? {
                  opacity: { type: 'spring', stiffness: 300, damping: 25 },
                  scale: {
                    repeat: Infinity,
                    duration: 1.5,
                    ease: 'easeInOut',
                  },
                }
              : { type: 'spring', stiffness: 300, damping: 25 }
          }
        >
          {expectedRul}
        </motion.p>
      </AnimatePresence>

      <p className="mt-1 text-sm text-[hsl(215,12%,58%)]">
        cycles remaining
      </p>

      {/* Confidence interval display */}
      {margin !== null && (
        <p className="mt-2 text-sm text-[hsl(215,12%,58%)]">
          ± {Math.round(margin)} cycles (90% CI)
        </p>
      )}
    </div>
  );
}
