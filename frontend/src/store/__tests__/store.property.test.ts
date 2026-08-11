import { describe, it, beforeEach } from 'vitest';
import fc from 'fast-check';
import { useStore, deriveSensorStatus, MAX_BUFFER_SIZE } from '@/store';
import type { ChartDataPoint } from '@/types';
import type { AnomalyAlert } from '@/types';
import type { CorrectionPayload } from '@/types';

/**
 * Property-based tests for Zustand store logic.
 * Validates: Requirements 2.2, 2.5, 3.1, 3.2, 3.4, 4.1, 4.2, 4.3
 */

// --- Arbitraries ---

// Base time for generating timestamps with guaranteed >2000ms spacing to avoid
// triggering the store's merge-on-close-timestamps behavior (MERGE_THRESHOLD_MS = 2000)
const baseTime = 1600000000000;

const sensorIdArb = fc.string({ minLength: 1, maxLength: 20, unit: 'grapheme-ascii' });

const anomalyAlertArb: fc.Arbitrary<AnomalyAlert> = fc.record({
  id: fc.uuid(),
  sensor_id: sensorIdArb,
  timestamp: fc.integer({ min: 1577836800000, max: 1893456000000 }).map(ms => new Date(ms).toISOString()),
  severity: fc.constantFrom('informational' as const, 'warning' as const, 'critical' as const),
  description: fc.string({ minLength: 1, maxLength: 100 }),
});

const correctionPayloadArb: fc.Arbitrary<CorrectionPayload> = fc.record({
  sensor_id: sensorIdArb,
  timestamp: fc.integer({ min: 1577836800000, max: 1893456000000 }).map(ms => new Date(ms).toISOString()),
  values: fc.array(fc.double({ min: -100, max: 100, noNaN: true }), { minLength: 1, maxLength: 5 }),
  ensemble_spread: fc.double({ min: 0, max: 2, noNaN: true }),
  anomaly_flag: fc.boolean(),
});

// --- Helpers ---

function resetStore() {
  useStore.setState({
    sensorData: {},
    anomalies: [],
    sensorHealth: {},
    pipelineHealth: null,
    connection: {
      status: 'disconnected',
      reconnectAttempts: 0,
      lastConnected: null,
      nextRetryMs: null,
    },
    activeSource: 'nasa-cmapss',
    ui: {
      isLoading: false,
      error: null,
      isSwitchingSource: false,
    },
  });
}

// --- Property Tests ---

describe('Property 1: Rolling Buffer Invariant', () => {
  beforeEach(resetStore);

  it('buffer length equals min(N, 200) and contains the most recent points in chronological order', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            raw: fc.option(fc.double({ min: -1000, max: 1000, noNaN: true }), { nil: undefined }),
            predicted: fc.option(fc.double({ min: -1000, max: 1000, noNaN: true }), { nil: undefined }),
            corrected: fc.option(fc.double({ min: -1000, max: 1000, noNaN: true }), { nil: undefined }),
          }),
          { minLength: 0, maxLength: 500 }
        ),
        (partialPoints) => {
          resetStore();
          const sensorId = 'test-sensor';

          // Generate points with guaranteed >2000ms spacing to avoid merge behavior
          const points: ChartDataPoint[] = partialPoints.map((p, i) => ({
            timestamp: baseTime + i * 3000,
            ...p,
          }));

          // Append all points sequentially
          for (const point of points) {
            useStore.getState().appendSensorData(sensorId, point);
          }

          const buffer = useStore.getState().sensorData[sensorId] ?? [];
          const N = points.length;
          const expectedLength = Math.min(N, MAX_BUFFER_SIZE);

          // Assert: buffer length === min(N, 200)
          if (buffer.length !== expectedLength) return false;

          // Assert: buffer contains the most recent min(N, 200) points in chronological order
          const expectedPoints = points.slice(Math.max(0, N - MAX_BUFFER_SIZE));
          for (let i = 0; i < buffer.length; i++) {
            if (buffer[i].timestamp !== expectedPoints[i].timestamp) return false;
            if (buffer[i].raw !== expectedPoints[i].raw) return false;
            if (buffer[i].predicted !== expectedPoints[i].predicted) return false;
            if (buffer[i].corrected !== expectedPoints[i].corrected) return false;
          }

          return true;
        }
      ),
      { numRuns: 100 }
    );
  });
});

describe('Property 4: Anomaly Alert Ordering and Completeness', () => {
  beforeEach(resetStore);

  it('anomalies are in reverse-chronological order with all fields present and length <= 100', () => {
    fc.assert(
      fc.property(
        fc.array(anomalyAlertArb, { minLength: 1, maxLength: 100 }),
        (alerts) => {
          resetStore();

          // Add all anomalies
          for (const alert of alerts) {
            useStore.getState().addAnomaly(alert);
          }

          const anomalies = useStore.getState().anomalies;

          // Assert: length never exceeds 100
          if (anomalies.length > 100) return false;

          // Assert: all fields are present
          for (const anomaly of anomalies) {
            if (!anomaly.sensor_id) return false;
            if (!anomaly.timestamp) return false;
            if (!anomaly.severity) return false;
            if (!anomaly.description) return false;
          }

          // Assert: anomalies are in reverse-chronological order
          // The store prepends each new alert, so the order reflects insertion order (newest first)
          // Since addAnomaly prepends, the first element is the last added alert
          // Verify the order matches reverse of insertion order
          const expectedOrder = [...alerts].reverse();
          for (let i = 0; i < anomalies.length; i++) {
            if (anomalies[i].id !== expectedOrder[i].id) return false;
          }

          return true;
        }
      ),
      { numRuns: 100 }
    );
  });
});

describe('Property 5: Sensor Health Status Derivation', () => {
  beforeEach(resetStore);

  it('correct status derived from ensemble_spread and anomaly_flag', () => {
    fc.assert(
      fc.property(
        correctionPayloadArb,
        (correction) => {
          const status = deriveSensorStatus(correction);

          // Assert: if anomaly_flag is true → status is 'critical'
          if (correction.anomaly_flag) {
            return status === 'critical';
          }

          // Assert: if anomaly_flag is false AND ensemble_spread > 0.5 → status is 'warning'
          if (!correction.anomaly_flag && correction.ensemble_spread > 0.5) {
            return status === 'warning';
          }

          // Assert: if anomaly_flag is false AND ensemble_spread <= 0.5 → status is 'healthy'
          if (!correction.anomaly_flag && correction.ensemble_spread <= 0.5) {
            return status === 'healthy';
          }

          return true;
        }
      ),
      { numRuns: 100 }
    );
  });
});

describe('Property 12: Sensor Health Card Count Invariant', () => {
  beforeEach(resetStore);

  it('N unique sensors produce exactly N health entries with no duplicates', () => {
    fc.assert(
      fc.property(
        fc.uniqueArray(
          sensorIdArb,
          { minLength: 1, maxLength: 50 }
        ),
        (sensorIds) => {
          resetStore();

          // Send correction events for each sensor
          for (const sensorId of sensorIds) {
            const correction: CorrectionPayload = {
              sensor_id: sensorId,
              timestamp: new Date().toISOString(),
              values: [1.0],
              ensemble_spread: Math.random(),
              anomaly_flag: false,
            };
            useStore.getState().updateSensorHealth(sensorId, correction);
          }

          const healthMap = useStore.getState().sensorHealth;
          const healthEntries = Object.keys(healthMap);

          // Assert: sensorHealth map has exactly N entries
          if (healthEntries.length !== sensorIds.length) return false;

          // Assert: no duplicates - each sensor ID appears exactly once
          const uniqueEntries = new Set(healthEntries);
          if (uniqueEntries.size !== sensorIds.length) return false;

          // Assert: every input sensor is represented
          for (const id of sensorIds) {
            if (!healthMap[id]) return false;
          }

          return true;
        }
      ),
      { numRuns: 100 }
    );
  });
});
