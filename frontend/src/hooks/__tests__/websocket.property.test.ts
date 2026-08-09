import { describe, it, expect, beforeEach } from 'vitest';
import fc from 'fast-check';
import { computeBackoffDelay } from '@/lib/websocket-utils';
import { useStore } from '@/store';
import type {
  TelemetryPayload,
  PredictionPayload,
  CorrectionPayload,
  AnomalyPayload,
  WebSocketMessage,
} from '@/types';

/**
 * Property-based tests for WebSocket utilities.
 * Validates: Requirements 8.2, 8.5
 */

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

/**
 * Mimics the message routing switch statement from useWebSocket hook.
 * Routes a WebSocket message to the appropriate store actions.
 */
function routeMessage(message: WebSocketMessage): void {
  const { appendSensorData, addAnomaly, updateSensorHealth } = useStore.getState();

  switch (message.type) {
    case 'telemetry': {
      const payload = message.payload as TelemetryPayload;
      appendSensorData(payload.sensor_id, {
        timestamp: new Date(payload.timestamp).getTime(),
        raw: payload.value,
      });
      break;
    }
    case 'prediction': {
      const payload = message.payload as PredictionPayload;
      appendSensorData(payload.sensor_id, {
        timestamp: new Date(payload.prediction_timestamp).getTime(),
        predicted: payload.state_vector[0],
      });
      break;
    }
    case 'correction': {
      const payload = message.payload as CorrectionPayload;
      appendSensorData(payload.sensor_id, {
        timestamp: new Date(payload.timestamp).getTime(),
        corrected: payload.values[0],
      });
      updateSensorHealth(payload.sensor_id, payload);
      break;
    }
    case 'anomaly': {
      const payload = message.payload as AnomalyPayload;
      addAnomaly({
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`,
        sensor_id: payload.sensor_id,
        timestamp: payload.timestamp,
        severity: payload.severity,
        description: payload.description,
      });
      break;
    }
  }
}

// --- Arbitraries ---

// Avoid Object prototype keys (toString, valueOf, etc.) which can collide with record lookups
const sensorIdArb = fc
  .stringMatching(/^[a-z][a-z0-9_-]{0,19}$/)
  .filter((s) => s.length >= 1);

// Generate ISO timestamps from unix millis to avoid Invalid Date issues with fc.date()
const isoTimestampArb = fc
  .integer({ min: 1577836800000, max: 1893456000000 }) // 2020-01-01 to 2030-01-01
  .map((ms) => new Date(ms).toISOString());

const telemetryPayloadArb: fc.Arbitrary<TelemetryPayload> = fc.record({
  sensor_id: sensorIdArb,
  timestamp: isoTimestampArb,
  measurement_type: fc.constantFrom('temperature', 'pressure', 'vibration', 'humidity'),
  value: fc.double({ min: -1000, max: 1000, noNaN: true }),
});

const predictionPayloadArb: fc.Arbitrary<PredictionPayload> = fc.record({
  sensor_id: sensorIdArb,
  prediction_timestamp: isoTimestampArb,
  state_vector: fc.array(fc.double({ min: -1000, max: 1000, noNaN: true }), { minLength: 1, maxLength: 5 }),
  model_used: fc.constantFrom('LSTM', 'XGBoost'),
  prediction_horizon_seconds: fc.integer({ min: 1, max: 3600 }),
});

const correctionPayloadArb: fc.Arbitrary<CorrectionPayload> = fc.record({
  sensor_id: sensorIdArb,
  timestamp: isoTimestampArb,
  values: fc.array(fc.double({ min: -1000, max: 1000, noNaN: true }), { minLength: 1, maxLength: 5 }),
  ensemble_spread: fc.double({ min: 0, max: 2, noNaN: true }),
  anomaly_flag: fc.boolean(),
});

const anomalyPayloadArb: fc.Arbitrary<AnomalyPayload> = fc.record({
  sensor_id: sensorIdArb,
  timestamp: isoTimestampArb,
  severity: fc.constantFrom('informational' as const, 'warning' as const, 'critical' as const),
  description: fc.string({ minLength: 1, maxLength: 100 }),
});

const websocketMessageArb: fc.Arbitrary<WebSocketMessage> = fc.oneof(
  telemetryPayloadArb.map((payload) => ({ type: 'telemetry' as const, payload })),
  predictionPayloadArb.map((payload) => ({ type: 'prediction' as const, payload })),
  correctionPayloadArb.map((payload) => ({ type: 'correction' as const, payload })),
  anomalyPayloadArb.map((payload) => ({ type: 'anomaly' as const, payload })),
);

// --- Property Tests ---

describe('Feature: dashboard-frontend, Property 2: Exponential Backoff Computation', () => {
  /**
   * **Validates: Requirements 8.2**
   *
   * For any number of consecutive reconnection attempts N (where N >= 1),
   * the computed reconnection delay SHALL equal min(1000 * 2^(N-1), 30000) ms.
   */

  it('computeBackoffDelay(N) === min(1000 * 2^(N-1), 30000) ms', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 100 }),
        (attempt) => {
          const delay = computeBackoffDelay(attempt);
          const expected = Math.min(1000 * Math.pow(2, attempt - 1), 30000);
          return delay === expected;
        }
      ),
      { numRuns: 100 }
    );
  });

  it('delay starts at 1000ms for N=1', () => {
    fc.assert(
      fc.property(
        fc.constant(1),
        () => {
          return computeBackoffDelay(1) === 1000;
        }
      ),
      { numRuns: 100 }
    );
  });

  it('delay never exceeds 30000ms', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 100 }),
        (attempt) => {
          const delay = computeBackoffDelay(attempt);
          return delay <= 30000;
        }
      ),
      { numRuns: 100 }
    );
  });

  it('delay doubles with each attempt until cap', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 99 }),
        (attempt) => {
          const currentDelay = computeBackoffDelay(attempt);
          const nextDelay = computeBackoffDelay(attempt + 1);

          // If current delay is already at cap, next should also be at cap
          if (currentDelay >= 30000) {
            return nextDelay === 30000;
          }

          // Otherwise, next delay should be double
          return nextDelay === Math.min(currentDelay * 2, 30000);
        }
      ),
      { numRuns: 100 }
    );
  });
});

describe('Feature: dashboard-frontend, Property 3: WebSocket Message Routing', () => {
  /**
   * **Validates: Requirements 8.5**
   *
   * For any valid WebSocket message with type field in
   * {"telemetry", "prediction", "correction", "anomaly"},
   * the message dispatcher SHALL route the payload to the
   * corresponding Zustand store slice without data loss.
   */

  beforeEach(resetStore);

  it('"telemetry" messages end up in sensorData with raw value', () => {
    fc.assert(
      fc.property(
        telemetryPayloadArb,
        (payload) => {
          resetStore();

          const message: WebSocketMessage = { type: 'telemetry', payload };
          routeMessage(message);

          const state = useStore.getState();
          const sensorBuffer = state.sensorData[payload.sensor_id];

          // Assert: data was routed to sensorData
          expect(sensorBuffer).toBeDefined();
          expect(sensorBuffer.length).toBe(1);

          // Assert: raw value matches payload
          const point = sensorBuffer[0];
          expect(point.raw).toBe(payload.value);
          expect(point.timestamp).toBe(new Date(payload.timestamp).getTime());
        }
      ),
      { numRuns: 100 }
    );
  });

  it('"prediction" messages end up in sensorData with predicted value', () => {
    fc.assert(
      fc.property(
        predictionPayloadArb,
        (payload) => {
          resetStore();

          const message: WebSocketMessage = { type: 'prediction', payload };
          routeMessage(message);

          const state = useStore.getState();
          const sensorBuffer = state.sensorData[payload.sensor_id];

          // Assert: data was routed to sensorData
          expect(sensorBuffer).toBeDefined();
          expect(sensorBuffer.length).toBe(1);

          // Assert: predicted value matches first element of state_vector
          const point = sensorBuffer[0];
          expect(point.predicted).toBe(payload.state_vector[0]);
          expect(point.timestamp).toBe(new Date(payload.prediction_timestamp).getTime());
        }
      ),
      { numRuns: 100 }
    );
  });

  it('"correction" messages end up in sensorData with corrected value AND sensorHealth is updated', () => {
    fc.assert(
      fc.property(
        correctionPayloadArb,
        (payload) => {
          resetStore();

          const message: WebSocketMessage = { type: 'correction', payload };
          routeMessage(message);

          const state = useStore.getState();
          const sensorBuffer = state.sensorData[payload.sensor_id];

          // Assert: data was routed to sensorData
          expect(sensorBuffer).toBeDefined();
          expect(sensorBuffer.length).toBe(1);

          // Assert: corrected value matches first element of values array
          const point = sensorBuffer[0];
          expect(point.corrected).toBe(payload.values[0]);
          expect(point.timestamp).toBe(new Date(payload.timestamp).getTime());

          // Assert: sensorHealth was updated
          const health = state.sensorHealth[payload.sensor_id];
          expect(health).toBeDefined();
          expect(health.sensor_id).toBe(payload.sensor_id);

          // Assert: health status correctly derived
          if (payload.anomaly_flag) {
            expect(health.status).toBe('critical');
          } else if (payload.ensemble_spread > 0.5) {
            expect(health.status).toBe('warning');
          } else {
            expect(health.status).toBe('healthy');
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it('"anomaly" messages end up in anomalies array', () => {
    fc.assert(
      fc.property(
        anomalyPayloadArb,
        (payload) => {
          resetStore();

          const message: WebSocketMessage = { type: 'anomaly', payload };
          routeMessage(message);

          const state = useStore.getState();

          // Assert: anomaly was added to the anomalies array
          expect(state.anomalies.length).toBe(1);

          const anomaly = state.anomalies[0];
          expect(anomaly.sensor_id).toBe(payload.sensor_id);
          expect(anomaly.timestamp).toBe(payload.timestamp);
          expect(anomaly.severity).toBe(payload.severity);
          expect(anomaly.description).toBe(payload.description);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('routing preserves data for all message types without loss', () => {
    fc.assert(
      fc.property(
        fc.array(websocketMessageArb, { minLength: 1, maxLength: 20 }),
        (messages) => {
          resetStore();

          // Count expected outcomes
          let expectedAnomalyCount = 0;
          const expectedSensorDataSensors = new Set<string>();

          for (const msg of messages) {
            routeMessage(msg);

            if (msg.type === 'anomaly') {
              expectedAnomalyCount++;
            } else {
              const payload = msg.payload as TelemetryPayload | PredictionPayload | CorrectionPayload;
              expectedSensorDataSensors.add(payload.sensor_id);
            }
          }

          const state = useStore.getState();

          // Assert: all anomaly messages ended up in anomalies
          expect(state.anomalies.length).toBe(expectedAnomalyCount);

          // Assert: all sensors that received telemetry/prediction/correction have data
          for (const sensorId of expectedSensorDataSensors) {
            expect(state.sensorData[sensorId]).toBeDefined();
            expect(state.sensorData[sensorId].length).toBeGreaterThan(0);
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});
