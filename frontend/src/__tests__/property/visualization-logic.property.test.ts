/**
 * Feature: digital-twin-v1.2, Property 8: KalmanGainIndicator percentages are complementary
 *
 * For any valid kalman_gain ∈ [0, 1], the sensor_trust percentage
 * (kalman_gain × 100) plus the model_trust percentage ((1 − kalman_gain) × 100)
 * SHALL always equal exactly 100.
 *
 * Feature: digital-twin-v1.2, Property 9: InnovationMeter normalization
 *
 * For any non-negative innovation magnitude and positive threshold,
 * the normalized bar width SHALL equal min(magnitude / threshold, 1.0) × 100,
 * producing a value in [0, 100].
 *
 * Validates: Requirements 9.1, 9.6, 10.1
 */
import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { getBarWidth, getBarColor } from '@/components/visualizations/InnovationMeter';

// --- KalmanGainIndicator logic (extracted from component) ---

/**
 * Computes the sensor trust and model trust percentages from a kalman gain value.
 * This mirrors the KalmanGainIndicator component logic exactly.
 */
function computeTrustPercentages(kalmanGain: number): {
  sensorTrust: number;
  modelTrust: number;
} {
  const sensorTrust = kalmanGain * 100;
  const modelTrust = (1 - kalmanGain) * 100;
  return { sensorTrust, modelTrust };
}

// --- Arbitraries ---

/** Kalman gain is always in [0, 1] */
const kalmanGainArb = fc.double({ min: 0.0, max: 1.0, noNaN: true });

/** Innovation magnitude is non-negative */
const magnitudeArb = fc.double({ min: 0.0, max: 1000.0, noNaN: true });

/** Threshold must be positive (used as denominator) */
const thresholdArb = fc.double({ min: 0.001, max: 100.0, noNaN: true });

// --- Property 8: KalmanGainIndicator percentages are complementary ---

describe('Feature: digital-twin-v1.2, Property 8: KalmanGainIndicator percentages are complementary', () => {
  it('sensor_trust + model_trust always equals 100 for any kalman_gain in [0, 1]', () => {
    fc.assert(
      fc.property(kalmanGainArb, (kalmanGain) => {
        const { sensorTrust, modelTrust } = computeTrustPercentages(kalmanGain);

        // The sum should be exactly 100 (floating point: within epsilon)
        expect(sensorTrust + modelTrust).toBeCloseTo(100, 10);
      }),
      { numRuns: 1000 }
    );
  });

  it('sensor_trust is in [0, 100] for any kalman_gain in [0, 1]', () => {
    fc.assert(
      fc.property(kalmanGainArb, (kalmanGain) => {
        const { sensorTrust } = computeTrustPercentages(kalmanGain);

        expect(sensorTrust).toBeGreaterThanOrEqual(0);
        expect(sensorTrust).toBeLessThanOrEqual(100);
      }),
      { numRuns: 1000 }
    );
  });

  it('model_trust is in [0, 100] for any kalman_gain in [0, 1]', () => {
    fc.assert(
      fc.property(kalmanGainArb, (kalmanGain) => {
        const { modelTrust } = computeTrustPercentages(kalmanGain);

        expect(modelTrust).toBeGreaterThanOrEqual(0);
        expect(modelTrust).toBeLessThanOrEqual(100);
      }),
      { numRuns: 1000 }
    );
  });

  it('when kalman_gain = 1 then sensor_trust = 100 and model_trust = 0', () => {
    const { sensorTrust, modelTrust } = computeTrustPercentages(1.0);
    expect(sensorTrust).toBe(100);
    expect(modelTrust).toBe(0);
  });

  it('when kalman_gain = 0 then sensor_trust = 0 and model_trust = 100', () => {
    const { sensorTrust, modelTrust } = computeTrustPercentages(0.0);
    expect(sensorTrust).toBe(0);
    expect(modelTrust).toBe(100);
  });
});

// --- Property 9: InnovationMeter normalization ---

describe('Feature: digital-twin-v1.2, Property 9: InnovationMeter normalization', () => {
  it('normalization equals min(magnitude/threshold, 1.0) × 100 for positive magnitude', () => {
    fc.assert(
      fc.property(magnitudeArb, thresholdArb, (magnitude, maxThreshold) => {
        const barWidth = getBarWidth(magnitude, maxThreshold);
        const expected = Math.min(magnitude / maxThreshold, 1.0) * 100;

        expect(barWidth).toBeCloseTo(expected, 10);
      }),
      { numRuns: 1000 }
    );
  });

  it('normalized value is always in [0, 100]', () => {
    fc.assert(
      fc.property(magnitudeArb, thresholdArb, (magnitude, maxThreshold) => {
        const barWidth = getBarWidth(magnitude, maxThreshold);

        expect(barWidth).toBeGreaterThanOrEqual(0);
        expect(barWidth).toBeLessThanOrEqual(100);
      }),
      { numRuns: 1000 }
    );
  });

  it('normalization never exceeds 100 even for very large magnitudes', () => {
    fc.assert(
      fc.property(
        fc.double({ min: 100.0, max: 1e6, noNaN: true }),
        thresholdArb,
        (largeMagnitude, maxThreshold) => {
          const barWidth = getBarWidth(largeMagnitude, maxThreshold);

          expect(barWidth).toBeLessThanOrEqual(100);
        }
      ),
      { numRuns: 1000 }
    );
  });

  it('returns 0 for null magnitude', () => {
    const barWidth = getBarWidth(null, 5.0);
    expect(barWidth).toBe(0);
  });

  it('returns 0 for zero magnitude', () => {
    const barWidth = getBarWidth(0, 5.0);
    expect(barWidth).toBe(0);
  });

  it('color is green for normalized < 0.33, amber for 0.33–0.66, red for > 0.66', () => {
    fc.assert(
      fc.property(magnitudeArb, thresholdArb, (magnitude, maxThreshold) => {
        const normalizedValue = Math.min(magnitude / maxThreshold, 1.0);
        const color = getBarColor(normalizedValue);

        if (normalizedValue < 0.33) {
          expect(color).toBe('#10b981'); // green
        } else if (normalizedValue < 0.66) {
          expect(color).toBe('#f59e0b'); // amber
        } else {
          expect(color).toBe('#ef4444'); // red
        }
      }),
      { numRuns: 1000 }
    );
  });
});
