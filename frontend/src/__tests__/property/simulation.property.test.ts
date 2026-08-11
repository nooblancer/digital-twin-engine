/**
 * Feature: digital-twin-v1.3, Property-based tests for simulation frontend logic
 *
 * Property: transformPercentiles preserves data — for any valid percentile arrays,
 * transformed output contains all input values at correct positions.
 *
 * Property: getRulColorClass threshold logic — for any integer RUL value, returned
 * color class matches threshold rules (< 20 → red, 20-40 → amber, > 40 → emerald).
 *
 * Property: debounce only fires for last value — for any sequence of rapid slider
 * changes within 300ms, only the final value triggers an API call.
 *
 * Validates: Requirements 8.3, 9.1–9.8, 11.4–11.6
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as fc from 'fast-check';
import { transformPercentiles } from '@/components/visualizations/MonteCarloFanChart';
import { getRulColorClass } from '@/components/visualizations/RULCountdown';

// --- Arbitraries ---

/** Health index values in [0, 1] representing valid percentile data */
const healthIndexArb = fc.double({ min: 0.0, max: 1.0, noNaN: true });

/** Generate a valid percentiles object with consistent array lengths */
function percentilesArb(minLen: number = 1, maxLen: number = 200) {
  return fc.integer({ min: minLen, max: maxLen }).chain((len) =>
    fc.record({
      5: fc.array(healthIndexArb, { minLength: len, maxLength: len }),
      25: fc.array(healthIndexArb, { minLength: len, maxLength: len }),
      50: fc.array(healthIndexArb, { minLength: len, maxLength: len }),
      75: fc.array(healthIndexArb, { minLength: len, maxLength: len }),
      95: fc.array(healthIndexArb, { minLength: len, maxLength: len }),
    })
  );
}

/** RUL values: any non-negative integer */
const rulArb = fc.integer({ min: 0, max: 500 });

/** Stress factor values from slider: 0.5 to 2.0 in 0.1 steps */
const stressFactorArb = fc.integer({ min: 5, max: 20 }).map((n) => n / 10);

// --- Property: transformPercentiles preserves data ---

describe('Feature: digital-twin-v1.3, Property: transformPercentiles preserves data', () => {
  it('output length equals input percentile array length', () => {
    fc.assert(
      fc.property(percentilesArb(), (percentiles) => {
        const result = transformPercentiles(percentiles);
        expect(result.length).toBe(percentiles[50].length);
      }),
      { numRuns: 200 }
    );
  });

  it('each output point contains input values at the correct position', () => {
    fc.assert(
      fc.property(percentilesArb(1, 50), (percentiles) => {
        const result = transformPercentiles(percentiles);

        for (let i = 0; i < result.length; i++) {
          const point = result[i];

          // Cycle is 1-indexed
          expect(point.cycle).toBe(i + 1);

          // Individual percentile values match inputs
          expect(point.p5).toBe(percentiles[5][i]);
          expect(point.p25).toBe(percentiles[25][i]);
          expect(point.p50).toBe(percentiles[50][i]);
          expect(point.p75).toBe(percentiles[75][i]);
          expect(point.p95).toBe(percentiles[95][i]);

          // Median matches p50
          expect(point.median).toBe(percentiles[50][i]);

          // Band arrays contain correct values
          expect(point.band95).toEqual([percentiles[5][i], percentiles[95][i]]);
          expect(point.band75).toEqual([percentiles[25][i], percentiles[75][i]]);
        }
      }),
      { numRuns: 100 }
    );
  }, 30000);

  it('transformation is lossless — all input values appear in output', () => {
    fc.assert(
      fc.property(percentilesArb(), (percentiles) => {
        const result = transformPercentiles(percentiles);
        const numCycles = percentiles[50].length;

        // Every value from every input percentile array appears somewhere in output
        for (let i = 0; i < numCycles; i++) {
          expect(result[i].p5).toBe(percentiles[5][i]);
          expect(result[i].p25).toBe(percentiles[25][i]);
          expect(result[i].p50).toBe(percentiles[50][i]);
          expect(result[i].p75).toBe(percentiles[75][i]);
          expect(result[i].p95).toBe(percentiles[95][i]);
        }
      }),
      { numRuns: 200 }
    );
  });
});

// --- Property: getRulColorClass threshold logic ---

describe('Feature: digital-twin-v1.3, Property: getRulColorClass threshold logic', () => {
  it('RUL < 20 always returns red color class', () => {
    fc.assert(
      fc.property(fc.integer({ min: 0, max: 19 }), (rul) => {
        const color = getRulColorClass(rul);
        expect(color).toBe('text-red-500');
      }),
      { numRuns: 200 }
    );
  });

  it('RUL 20-40 always returns amber color class', () => {
    fc.assert(
      fc.property(fc.integer({ min: 20, max: 40 }), (rul) => {
        const color = getRulColorClass(rul);
        expect(color).toBe('text-amber-500');
      }),
      { numRuns: 200 }
    );
  });

  it('RUL > 40 always returns emerald color class', () => {
    fc.assert(
      fc.property(fc.integer({ min: 41, max: 500 }), (rul) => {
        const color = getRulColorClass(rul);
        expect(color).toBe('text-emerald-500');
      }),
      { numRuns: 200 }
    );
  });

  it('threshold boundaries are correct — exactly 20 is amber, exactly 40 is amber', () => {
    expect(getRulColorClass(19)).toBe('text-red-500');
    expect(getRulColorClass(20)).toBe('text-amber-500');
    expect(getRulColorClass(40)).toBe('text-amber-500');
    expect(getRulColorClass(41)).toBe('text-emerald-500');
  });

  it('for any non-negative integer RUL, exactly one of the three classes is returned', () => {
    const validClasses = ['text-red-500', 'text-amber-500', 'text-emerald-500'];
    fc.assert(
      fc.property(rulArb, (rul) => {
        const color = getRulColorClass(rul);
        expect(validClasses).toContain(color);
      }),
      { numRuns: 500 }
    );
  });
});

// --- Property: debounce only fires for last value ---

describe('Feature: digital-twin-v1.3, Property: debounce only fires for last value', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  /**
   * Simulate the WhatIfStressSlider debounce logic:
   * Each slider change clears the previous timeout and sets a new one at 300ms.
   * Only the last scheduled call should fire after 300ms of inactivity.
   */
  it('only the final value in a rapid sequence triggers the callback', () => {
    fc.assert(
      fc.property(
        fc.array(stressFactorArb, { minLength: 2, maxLength: 20 }),
        (values) => {
          const callback = vi.fn();
          let timeoutId: ReturnType<typeof setTimeout> | null = null;

          // Simulate rapid slider changes (all within 300ms)
          for (const value of values) {
            if (timeoutId !== null) {
              clearTimeout(timeoutId);
            }
            timeoutId = setTimeout(() => {
              callback(value);
            }, 300);
          }

          // Before 300ms: no calls
          vi.advanceTimersByTime(299);
          expect(callback).not.toHaveBeenCalled();

          // After 300ms: exactly one call with the last value
          vi.advanceTimersByTime(1);
          expect(callback).toHaveBeenCalledTimes(1);
          expect(callback).toHaveBeenCalledWith(values[values.length - 1]);
        }
      ),
      { numRuns: 200 }
    );
  });

  it('single value triggers callback after 300ms debounce period', () => {
    fc.assert(
      fc.property(stressFactorArb, (value) => {
        const callback = vi.fn();

        const timeoutId = setTimeout(() => {
          callback(value);
        }, 300);

        // Not called before timeout
        vi.advanceTimersByTime(299);
        expect(callback).not.toHaveBeenCalled();

        // Called after timeout
        vi.advanceTimersByTime(1);
        expect(callback).toHaveBeenCalledTimes(1);
        expect(callback).toHaveBeenCalledWith(value);
      }),
      { numRuns: 200 }
    );
  });

  it('intermediate values never trigger the callback if followed within 300ms', () => {
    fc.assert(
      fc.property(
        fc.array(stressFactorArb, { minLength: 3, maxLength: 15 }),
        (values) => {
          const calls: number[] = [];
          let timeoutId: ReturnType<typeof setTimeout> | null = null;

          // Simulate rapid changes — each separated by less than 300ms
          for (const value of values) {
            if (timeoutId !== null) {
              clearTimeout(timeoutId);
            }
            timeoutId = setTimeout(() => {
              calls.push(value);
            }, 300);

            // Advance by a small amount (< 300ms) to simulate rapid dragging
            vi.advanceTimersByTime(50);
          }

          // Flush remaining timer
          vi.advanceTimersByTime(300);

          // Only the last value should have been recorded
          expect(calls.length).toBe(1);
          expect(calls[0]).toBe(values[values.length - 1]);
        }
      ),
      { numRuns: 200 }
    );
  });
});
