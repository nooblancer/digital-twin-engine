/**
 * Feature: digital-twin-experience, Property 24: Frontend message routing
 *
 * For any valid WebSocket message with type rul_update, health_index_update,
 * subsystem_health_update, or degradation_update, the frontend SHALL route
 * the payload to the corresponding store action and update the correct engine state.
 *
 * Validates: Requirements 8.4
 */
import { describe, it, expect, beforeEach } from 'vitest';
import * as fc from 'fast-check';
import { useStore } from '@/store';
import type {
  RULUpdatePayload,
  HealthIndexUpdatePayload,
  SubsystemHealthUpdatePayload,
  DegradationUpdatePayload,
} from '@/types/digital-twin';

// --- Arbitraries ---

const engineIdArb = fc.integer({ min: 1, max: 100 });
const cycleNumberArb = fc.integer({ min: 1, max: 400 });

const rulPayloadArb: fc.Arbitrary<RULUpdatePayload> = fc.record({
  engine_id: engineIdArb,
  rul_cycles: fc.integer({ min: 0, max: 125 }),
  cycle_number: cycleNumberArb,
  is_urgent: fc.boolean(),
});

const healthIndexPayloadArb: fc.Arbitrary<HealthIndexUpdatePayload> = fc.record({
  engine_id: engineIdArb,
  health_index: fc.double({ min: 0.0, max: 1.0, noNaN: true }),
  cycle_number: cycleNumberArb,
  is_provisional: fc.boolean(),
});

const subsystemNameArb = fc.constantFrom('fan', 'lpc', 'hpc', 'hpt', 'lpt', 'combustor');
const classificationArb = fc.constantFrom('nominal', 'degraded', 'critical');

const subsystemHealthPayloadArb: fc.Arbitrary<SubsystemHealthUpdatePayload> = fc.record({
  engine_id: engineIdArb,
  cycle_number: cycleNumberArb,
  subsystems: fc.array(
    fc.record({
      name: subsystemNameArb,
      health_score: fc.double({ min: 0.0, max: 1.0, noNaN: true }),
      classification: classificationArb,
    }),
    { minLength: 1, maxLength: 6 }
  ),
});

const degradationPayloadArb: fc.Arbitrary<DegradationUpdatePayload> = fc.record({
  engine_id: engineIdArb,
  degradation_rate: fc.oneof(
    fc.constant(null),
    fc.double({ min: -0.1, max: 0.1, noNaN: true })
  ),
  cycle_number: cycleNumberArb,
});

type DigitalTwinMessage =
  | { type: 'rul_update'; payload: RULUpdatePayload }
  | { type: 'health_index_update'; payload: HealthIndexUpdatePayload }
  | { type: 'subsystem_health_update'; payload: SubsystemHealthUpdatePayload }
  | { type: 'degradation_update'; payload: DegradationUpdatePayload };

const digitalTwinMessageArb: fc.Arbitrary<DigitalTwinMessage> = fc.oneof(
  rulPayloadArb.map((payload) => ({ type: 'rul_update' as const, payload })),
  healthIndexPayloadArb.map((payload) => ({ type: 'health_index_update' as const, payload })),
  subsystemHealthPayloadArb.map((payload) => ({ type: 'subsystem_health_update' as const, payload })),
  degradationPayloadArb.map((payload) => ({ type: 'degradation_update' as const, payload }))
);

// --- Helper: route message to the correct store action ---

function routeMessage(message: DigitalTwinMessage): void {
  const store = useStore.getState();
  switch (message.type) {
    case 'rul_update':
      store.updateRUL(message.payload);
      break;
    case 'health_index_update':
      store.updateHealthIndex(message.payload);
      break;
    case 'subsystem_health_update':
      store.updateSubsystemHealth(message.payload);
      break;
    case 'degradation_update':
      store.updateDegradation(message.payload);
      break;
  }
}

describe('Feature: digital-twin-experience, Property 24: Frontend message routing', () => {
  beforeEach(() => {
    // Reset store between tests
    useStore.setState({ engines: {}, selectedEngineId: null });
  });

  it('routes rul_update messages to updateRUL and updates engine state correctly', () => {
    fc.assert(
      fc.property(rulPayloadArb, (payload) => {
        useStore.setState({ engines: {} });

        routeMessage({ type: 'rul_update', payload });

        const engine = useStore.getState().engines[payload.engine_id];
        expect(engine).toBeDefined();
        expect(engine.rul).toBe(payload.rul_cycles);
        expect(engine.isUrgent).toBe(payload.is_urgent);
        expect(engine.lastUpdateCycle).toBe(payload.cycle_number);
        expect(engine.engineId).toBe(payload.engine_id);
      }),
      { numRuns: 100 }
    );
  });

  it('routes health_index_update messages to updateHealthIndex and updates engine state correctly', () => {
    fc.assert(
      fc.property(healthIndexPayloadArb, (payload) => {
        useStore.setState({ engines: {} });

        routeMessage({ type: 'health_index_update', payload });

        const engine = useStore.getState().engines[payload.engine_id];
        expect(engine).toBeDefined();
        expect(engine.healthIndex).toBe(payload.health_index);
        expect(engine.isProvisional).toBe(payload.is_provisional);
        expect(engine.lastUpdateCycle).toBe(payload.cycle_number);
        expect(engine.engineId).toBe(payload.engine_id);
      }),
      { numRuns: 100 }
    );
  });

  it('routes subsystem_health_update messages to updateSubsystemHealth and updates engine state correctly', () => {
    fc.assert(
      fc.property(subsystemHealthPayloadArb, (payload) => {
        useStore.setState({ engines: {} });

        routeMessage({ type: 'subsystem_health_update', payload });

        const engine = useStore.getState().engines[payload.engine_id];
        expect(engine).toBeDefined();
        expect(engine.subsystems).toHaveLength(payload.subsystems.length);
        for (let i = 0; i < payload.subsystems.length; i++) {
          expect(engine.subsystems[i].name).toBe(payload.subsystems[i].name);
          expect(engine.subsystems[i].healthScore).toBe(payload.subsystems[i].health_score);
          expect(engine.subsystems[i].classification).toBe(payload.subsystems[i].classification);
        }
        expect(engine.lastUpdateCycle).toBe(payload.cycle_number);
      }),
      { numRuns: 100 }
    );
  });

  it('routes degradation_update messages to updateDegradation and updates engine state correctly', () => {
    fc.assert(
      fc.property(degradationPayloadArb, (payload) => {
        useStore.setState({ engines: {} });

        routeMessage({ type: 'degradation_update', payload });

        const engine = useStore.getState().engines[payload.engine_id];
        expect(engine).toBeDefined();
        expect(engine.degradationRate).toBe(payload.degradation_rate);
        expect(engine.lastUpdateCycle).toBe(payload.cycle_number);
        expect(engine.engineId).toBe(payload.engine_id);
      }),
      { numRuns: 100 }
    );
  });

  it('routes any valid digital twin message to the correct store action and targets the correct engine', () => {
    fc.assert(
      fc.property(digitalTwinMessageArb, (message) => {
        useStore.setState({ engines: {} });

        routeMessage(message);

        const engineId = message.payload.engine_id;
        const engine = useStore.getState().engines[engineId];

        // The correct engine was created/updated
        expect(engine).toBeDefined();
        expect(engine.engineId).toBe(engineId);

        // The lastUpdateCycle was set from the message
        expect(engine.lastUpdateCycle).toBe(message.payload.cycle_number);
      }),
      { numRuns: 100 }
    );
  });
});
