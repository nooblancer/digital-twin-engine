/**
 * Feature: digital-twin-v1.2, Property 6: Zustand store preserves all correction fields
 *
 * For any valid extended correction payload dispatched to the store, the
 * correctionHistory for that sensor_id SHALL contain a data point with
 * kalman_gain, innovation_magnitude, confidence_band_95, and raw_prediction
 * matching the payload values (or null if missing from payload).
 *
 * Feature: digital-twin-v1.2, Property 7: Correction history buffer respects maximum size
 *
 * For any sensor that has received N correction messages where N > 100, the
 * correctionHistory for that sensor SHALL contain exactly 100 entries,
 * retaining the most recent 100 data points in chronological order.
 *
 * Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
 */
import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { createStore } from 'zustand';
import {
  createCorrectionMetricsSlice,
  MAX_CORRECTION_HISTORY,
} from '@/store/correction-metrics';
import type { CorrectionMetricsSlice } from '@/store/correction-metrics';
import type { ExtendedCorrectionPayload } from '@/types/correction-metrics';

// --- Arbitraries ---

const sensorIdArb = fc.constantFrom(
  'sensor-001', 'sensor-002', 'sensor-003', 'sensor-004',
  'engine-001-hpc', 'engine-002-lpt', 'engine-003-fan'
);

// Use integer timestamps to avoid invalid date issues with fc.date() in fast-check v4
const timestampArb = fc.integer({
  min: new Date('2020-01-01').getTime(),
  max: new Date('2030-12-31').getTime(),
}).map((ms) => new Date(ms).toISOString());

const valuesArb = fc.array(fc.double({ min: -1000, max: 1000, noNaN: true }), {
  minLength: 1,
  maxLength: 5,
});

const ensembleSpreadArb = fc.double({ min: 0.0, max: 100.0, noNaN: true });

const kalmanGainArb = fc.oneof(
  fc.constant(undefined),
  fc.constant(null),
  fc.double({ min: 0.0, max: 1.0, noNaN: true })
);

const innovationMagnitudeArb = fc.oneof(
  fc.constant(undefined),
  fc.constant(null),
  fc.double({ min: 0.0, max: 50.0, noNaN: true })
);

const confidenceBand95Arb = fc.oneof(
  fc.constant(undefined),
  fc.constant(null),
  fc.tuple(
    fc.double({ min: -1000, max: 1000, noNaN: true }),
    fc.double({ min: -1000, max: 1000, noNaN: true })
  ).map(([a, b]): [number, number] => [Math.min(a, b), Math.max(a, b)])
);

const rawPredictionArb = fc.oneof(
  fc.constant(undefined),
  fc.constant(null),
  fc.double({ min: -1000, max: 1000, noNaN: true })
);

const correctionPayloadArb: fc.Arbitrary<ExtendedCorrectionPayload> = fc.record({
  sensor_id: sensorIdArb,
  timestamp: timestampArb,
  values: valuesArb,
  ensemble_spread: ensembleSpreadArb,
  anomaly_flag: fc.boolean(),
  kalman_gain: kalmanGainArb,
  innovation_magnitude: innovationMagnitudeArb,
  confidence_band_95: confidenceBand95Arb,
  raw_prediction: rawPredictionArb,
}) as fc.Arbitrary<ExtendedCorrectionPayload>;

// Fixed sensor ID payloads for buffer tests
function payloadWithSensorId(sensorId: string): fc.Arbitrary<ExtendedCorrectionPayload> {
  return fc.record({
    sensor_id: fc.constant(sensorId),
    timestamp: timestampArb,
    values: valuesArb,
    ensemble_spread: ensembleSpreadArb,
    anomaly_flag: fc.boolean(),
    kalman_gain: kalmanGainArb,
    innovation_magnitude: innovationMagnitudeArb,
    confidence_band_95: confidenceBand95Arb,
    raw_prediction: rawPredictionArb,
  }) as fc.Arbitrary<ExtendedCorrectionPayload>;
}

// Helper to create a fresh store for each test
function createTestStore() {
  return createStore<CorrectionMetricsSlice>(createCorrectionMetricsSlice);
}

describe('Feature: digital-twin-v1.2, Property 6: Zustand store preserves all correction fields', () => {
  it('stores kalman_gain matching the payload value (or null if missing)', () => {
    fc.assert(
      fc.property(correctionPayloadArb, (payload) => {
        const store = createTestStore();
        store.getState().updateCorrectionMetrics(payload);

        const state = store.getState();
        const history = state.correctionHistory[payload.sensor_id];

        expect(history).toBeDefined();
        expect(history.length).toBe(1);

        const point = history[0];
        const expectedKalmanGain = payload.kalman_gain ?? null;
        expect(point.kalman_gain).toBe(expectedKalmanGain);

        // Also verify latestKalmanGain
        expect(state.latestKalmanGain[payload.sensor_id]).toBe(expectedKalmanGain);
      }),
      { numRuns: 100 }
    );
  });

  it('stores innovation_magnitude matching the payload value (or null if missing)', () => {
    fc.assert(
      fc.property(correctionPayloadArb, (payload) => {
        const store = createTestStore();
        store.getState().updateCorrectionMetrics(payload);

        const state = store.getState();
        const history = state.correctionHistory[payload.sensor_id];
        const point = history[0];

        const expectedInnovation = payload.innovation_magnitude ?? null;
        expect(point.innovation_magnitude).toBe(expectedInnovation);
        expect(state.latestInnovation[payload.sensor_id]).toBe(expectedInnovation);
      }),
      { numRuns: 100 }
    );
  });

  it('stores confidence_band_95 matching the payload value (or null if missing)', () => {
    fc.assert(
      fc.property(correctionPayloadArb, (payload) => {
        const store = createTestStore();
        store.getState().updateCorrectionMetrics(payload);

        const state = store.getState();
        const history = state.correctionHistory[payload.sensor_id];
        const point = history[0];

        const expectedBand = payload.confidence_band_95 ?? null;
        expect(point.confidence_band_95).toEqual(expectedBand);
        expect(state.latestConfidenceBand[payload.sensor_id]).toEqual(expectedBand);
      }),
      { numRuns: 100 }
    );
  });

  it('stores raw_prediction matching the payload value (or null if missing)', () => {
    fc.assert(
      fc.property(correctionPayloadArb, (payload) => {
        const store = createTestStore();
        store.getState().updateCorrectionMetrics(payload);

        const state = store.getState();
        const history = state.correctionHistory[payload.sensor_id];
        const point = history[0];

        const expectedRawPred = payload.raw_prediction ?? null;
        expect(point.raw_prediction).toBe(expectedRawPred);
        expect(state.latestRawPrediction[payload.sensor_id]).toBe(expectedRawPred);
      }),
      { numRuns: 100 }
    );
  });

  it('stores corrected_value from values[0] and ensemble_spread correctly', () => {
    fc.assert(
      fc.property(correctionPayloadArb, (payload) => {
        const store = createTestStore();
        store.getState().updateCorrectionMetrics(payload);

        const history = store.getState().correctionHistory[payload.sensor_id];
        const point = history[0];

        expect(point.corrected_value).toBe(payload.values[0]);
        expect(point.ensemble_spread).toBe(payload.ensemble_spread);
      }),
      { numRuns: 100 }
    );
  });

  it('stores timestamp as numeric milliseconds from ISO string', () => {
    fc.assert(
      fc.property(correctionPayloadArb, (payload) => {
        const store = createTestStore();
        store.getState().updateCorrectionMetrics(payload);

        const history = store.getState().correctionHistory[payload.sensor_id];
        const point = history[0];

        const expectedTimestamp = new Date(payload.timestamp).getTime();
        expect(point.timestamp).toBe(expectedTimestamp);
      }),
      { numRuns: 100 }
    );
  });
});

describe('Feature: digital-twin-v1.2, Property 7: Correction history buffer respects maximum size', () => {
  it('buffer never exceeds MAX_CORRECTION_HISTORY entries per sensor', () => {
    const fixedSensorId = 'test-sensor-overflow';

    fc.assert(
      fc.property(
        fc.array(payloadWithSensorId(fixedSensorId), { minLength: 150, maxLength: 200 }),
        (payloads) => {
          const store = createTestStore();

          for (const payload of payloads) {
            store.getState().updateCorrectionMetrics(payload);
          }

          const history = store.getState().correctionHistory[fixedSensorId];
          expect(history.length).toBe(MAX_CORRECTION_HISTORY);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('retains the most recent entries when buffer overflows (FIFO eviction)', () => {
    const fixedSensorId = 'test-sensor-fifo';

    fc.assert(
      fc.property(
        fc.array(payloadWithSensorId(fixedSensorId), { minLength: 150, maxLength: 200 }),
        (payloads) => {
          const store = createTestStore();

          for (const payload of payloads) {
            store.getState().updateCorrectionMetrics(payload);
          }

          const history = store.getState().correctionHistory[fixedSensorId];

          // The last MAX_CORRECTION_HISTORY payloads should match the stored history
          const expectedPayloads = payloads.slice(-MAX_CORRECTION_HISTORY);

          expect(history.length).toBe(MAX_CORRECTION_HISTORY);

          for (let i = 0; i < history.length; i++) {
            const point = history[i];
            const expectedPayload = expectedPayloads[i];

            expect(point.corrected_value).toBe(expectedPayload.values[0]);
            expect(point.ensemble_spread).toBe(expectedPayload.ensemble_spread);
            expect(point.timestamp).toBe(new Date(expectedPayload.timestamp).getTime());
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it('buffer grows correctly up to MAX_CORRECTION_HISTORY before eviction begins', () => {
    const fixedSensorId = 'test-sensor-growth';

    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: MAX_CORRECTION_HISTORY }),
        fc.array(payloadWithSensorId(fixedSensorId), { minLength: 1, maxLength: 1 }),
        (count, [samplePayload]) => {
          const store = createTestStore();

          // Dispatch exactly `count` payloads (count <= MAX_CORRECTION_HISTORY)
          for (let i = 0; i < count; i++) {
            store.getState().updateCorrectionMetrics({
              ...samplePayload,
              timestamp: new Date(2024, 0, 1, 0, 0, i).toISOString(),
            });
          }

          const history = store.getState().correctionHistory[fixedSensorId];
          expect(history.length).toBe(count);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('different sensors maintain independent buffers', () => {
    fc.assert(
      fc.property(
        fc.array(payloadWithSensorId('sensor-A'), { minLength: 110, maxLength: 130 }),
        fc.array(payloadWithSensorId('sensor-B'), { minLength: 50, maxLength: 80 }),
        (payloadsA, payloadsB) => {
          const store = createTestStore();

          // Dispatch all payloads for sensor A
          for (const payload of payloadsA) {
            store.getState().updateCorrectionMetrics(payload);
          }

          // Dispatch all payloads for sensor B
          for (const payload of payloadsB) {
            store.getState().updateCorrectionMetrics(payload);
          }

          const historyA = store.getState().correctionHistory['sensor-A'];
          const historyB = store.getState().correctionHistory['sensor-B'];

          // Sensor A overflowed: exactly MAX_CORRECTION_HISTORY
          expect(historyA.length).toBe(MAX_CORRECTION_HISTORY);

          // Sensor B did not overflow: length equals number dispatched
          expect(historyB.length).toBe(payloadsB.length);
        }
      ),
      { numRuns: 100 }
    );
  });
});
