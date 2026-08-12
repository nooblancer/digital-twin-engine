'use client';

import { useEffect, useRef, useState, useMemo } from 'react';
import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  ResponsiveContainer,
} from 'recharts';
import type { ActiveDotProps } from 'recharts';
import { motion } from 'framer-motion';
import { usePrefersReducedMotion } from '@/lib/animations';

/**
 * BeforeAfterChart — Side-by-side comparison showing noisy prediction
 * vs smooth EnKF-corrected prediction. Demonstrates the value of the
 * digital twin's correction engine visually.
 *
 * Landing page "How It's Different" section.
 * Validates: Requirements 9.5, 14.4, 15.1
 */

// --- Types ---

interface ChartDataPoint {
  step: number;
  value: number;
}

// --- Deterministic seeded PRNG for reproducible synthetic data ---

function seededRandom(seed: number): () => number {
  let state = seed;
  return () => {
    // Mulberry32 algorithm
    state |= 0;
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// --- Synthetic data generation ---

const DATA_POINTS = 50;
const SEED_NOISY = 42;
const SEED_CORRECTED = 7;

function generateBaseSignal(count: number): number[] {
  const signal: number[] = [];
  for (let i = 0; i < count; i++) {
    // Sinusoidal base signal representing true engine state
    signal.push(
      500 + 80 * Math.sin((i / count) * Math.PI * 2) + 30 * Math.sin((i / count) * Math.PI * 5)
    );
  }
  return signal;
}

export function generateNoisyData(): ChartDataPoint[] {
  const base = generateBaseSignal(DATA_POINTS);
  const rng = seededRandom(SEED_NOISY);
  return base.map((val, i) => ({
    step: i,
    value: val + (rng() - 0.5) * 120, // large noise amplitude
  }));
}

export function generateCorrectedData(): ChartDataPoint[] {
  const base = generateBaseSignal(DATA_POINTS);
  const rng = seededRandom(SEED_CORRECTED);
  return base.map((val, i) => ({
    step: i,
    value: val + (rng() - 0.5) * 15, // small residual noise
  }));
}

// --- Glow Dot renderer (follows EnhancedLineChart pattern) ---

function makeGlowDot(color: string, dataLength: number) {
  return function GlowDotRenderer(props: ActiveDotProps) {
    const { cx, cy, index } = props;
    if (cx == null || cy == null || index == null) return null;

    const isLast = index === dataLength - 1;
    if (!isLast) return null;

    return (
      <g>
        <circle cx={cx} cy={cy} r={8} fill={color} opacity={0.25} />
        <circle cx={cx} cy={cy} r={4} fill={color} />
      </g>
    );
  };
}

// --- Constants ---

const ACCENT_PRIMARY = '#00d4ff';
const MUTED_COLOR = '#6b7280'; // gray-500 — dim/muted for noisy line
const NOISY_GRADIENT_ID = 'before-after-noisy-gradient';
const CORRECTED_GRADIENT_ID = 'before-after-corrected-gradient';

// --- Sub-components ---

interface ChartPanelProps {
  title: string;
  subtitle: string;
  data: ChartDataPoint[];
  lineColor: string;
  gradientId: string;
  showGlowDot: boolean;
  isVisible: boolean;
  prefersReducedMotion: boolean;
}

function ChartPanel({
  title,
  subtitle,
  data,
  lineColor,
  gradientId,
  showGlowDot,
  isVisible,
  prefersReducedMotion,
}: ChartPanelProps) {
  const shouldAnimate = isVisible && !prefersReducedMotion;

  return (
    <div className="flex-1 min-w-0">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-[#e2e8f0] tracking-tight">
          {title}
        </h3>
        <p className="text-xs text-[#a0aec0] mt-0.5">{subtitle}</p>
      </div>
      <div className="rounded-lg border border-white/[0.06] bg-[#12141a] p-3">
        <ResponsiveContainer width="100%" height={200}>
          <ComposedChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 8 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={lineColor} stopOpacity={0.25} />
                <stop offset="100%" stopColor={lineColor} stopOpacity={0} />
              </linearGradient>
            </defs>

            <CartesianGrid stroke="hsl(220, 10%, 20%)" strokeDasharray="3 3" />

            <XAxis
              dataKey="step"
              stroke="hsl(215, 12%, 58%)"
              tick={{ fontSize: 10 }}
              label={{ value: 'Cycle', position: 'insideBottom', offset: -4, style: { fontSize: 10, fill: '#a0aec0' } }}
            />
            <YAxis
              stroke="hsl(215, 12%, 58%)"
              tick={{ fontSize: 10 }}
              label={{ value: 'RUL Estimate', angle: -90, position: 'insideLeft', style: { fontSize: 10, fill: '#a0aec0' } }}
            />

            <Area
              type="monotone"
              dataKey="value"
              stroke="none"
              fill={`url(#${gradientId})`}
              fillOpacity={1}
              isAnimationActive={shouldAnimate}
              animationDuration={1500}
            />

            <Line
              type="monotone"
              dataKey="value"
              stroke={lineColor}
              strokeWidth={2}
              dot={false}
              activeDot={
                showGlowDot ? makeGlowDot(lineColor, data.length) : undefined
              }
              isAnimationActive={shouldAnimate}
              animationDuration={1500}
              animationEasing="ease-in-out"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// --- Main Component ---

export function BeforeAfterChart() {
  const prefersReducedMotion = usePrefersReducedMotion();
  const containerRef = useRef<HTMLDivElement>(null);
  const [isVisible, setIsVisible] = useState(false);

  // Intersection Observer to trigger animation on scroll-into-view
  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    // If reduced motion, show immediately
    if (prefersReducedMotion) {
      setIsVisible(true);
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setIsVisible(true);
            observer.unobserve(element);
          }
        });
      },
      { threshold: 0.3 }
    );

    observer.observe(element);

    return () => {
      observer.unobserve(element);
    };
  }, [prefersReducedMotion]);

  // Memoize data so it's deterministic and stable across re-renders
  const noisyData = useMemo(() => generateNoisyData(), []);
  const correctedData = useMemo(() => generateCorrectedData(), []);

  // Calculate noise reduction percentage from variance ratio
  const noiseReduction = useMemo(() => {
    const noisyValues = noisyData.map((d) => d.value);
    const correctedValues = correctedData.map((d) => d.value);

    const mean = (arr: number[]) => arr.reduce((a, b) => a + b, 0) / arr.length;
    const variance = (arr: number[]) => {
      const m = mean(arr);
      return arr.reduce((sum, v) => sum + (v - m) ** 2, 0) / arr.length;
    };

    const noisyVar = variance(noisyValues);
    const correctedVar = variance(correctedValues);
    const reduction = ((noisyVar - correctedVar) / noisyVar) * 100;
    return Math.round(reduction);
  }, [noisyData, correctedData]);

  const containerVariants = {
    hidden: { opacity: 0, y: 20 },
    visible: {
      opacity: 1,
      y: 0,
      transition: { duration: 0.6, ease: 'easeOut' as const },
    },
  };

  return (
    <motion.div
      ref={containerRef}
      role="region"
      aria-label="Before and after comparison: prediction quality with and without digital twin correction"
      initial={prefersReducedMotion ? 'visible' : 'hidden'}
      animate={isVisible ? 'visible' : 'hidden'}
      variants={containerVariants}
      className="w-full"
    >
      {/* Section heading */}
      <div className="text-center mb-6">
        <h2 className="text-xl font-bold text-[#e2e8f0] tracking-tight">
          How It&apos;s Different
        </h2>
        <p className="text-sm text-[#a0aec0] mt-1">
          Side-by-side comparison of raw ML predictions vs EnKF-corrected output
        </p>
      </div>

      {/* Charts grid */}
      <div className="flex flex-col md:flex-row gap-6">
        <ChartPanel
          title="Without Digital Twin"
          subtitle="Raw ML prediction — noisy, unreliable"
          data={noisyData}
          lineColor={MUTED_COLOR}
          gradientId={NOISY_GRADIENT_ID}
          showGlowDot={false}
          isVisible={isVisible}
          prefersReducedMotion={prefersReducedMotion}
        />

        <ChartPanel
          title="With Digital Twin"
          subtitle="EnKF-corrected — smooth, accurate"
          data={correctedData}
          lineColor={ACCENT_PRIMARY}
          gradientId={CORRECTED_GRADIENT_ID}
          showGlowDot={true}
          isVisible={isVisible}
          prefersReducedMotion={prefersReducedMotion}
        />
      </div>

      {/* Improvement annotation */}
      <motion.div
        className="mt-4 flex justify-center"
        initial={prefersReducedMotion ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.9 }}
        animate={
          isVisible
            ? { opacity: 1, scale: 1, transition: { delay: 0.8, duration: 0.4 } }
            : { opacity: 0, scale: 0.9 }
        }
      >
        <div className="inline-flex items-center gap-2 rounded-full border border-[#00d4ff]/30 bg-[#00d4ff]/[0.08] px-4 py-1.5">
          <span className="text-[#00d4ff] font-bold text-sm">
            {noiseReduction}% noise reduction
          </span>
          <span className="text-[#a0aec0] text-xs">
            with EnKF correction
          </span>
        </div>
      </motion.div>
    </motion.div>
  );
}
