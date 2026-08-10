/**
 * Feature: digital-twin-experience, Property 25: Snapshot restore round-trip
 *
 * For any engine state, serializing it to a snapshot response and then restoring
 * from that snapshot SHALL produce a frontend state equivalent to the original engine state.
 *
 * Validates: Requirements 8.5
 */
import { describe, it, expect, beforeEach } from 'vitest';
import * as fc from 'fast-check';
import { useStore } from '@/store';
import type { EngineSnapshot, EngineState } from '@/types/digital-twin';

// --- Arbitraries ---

const engineIdArb = fc.integer({ min: 1, max: 100 });
const cycleNumberArb = fc.integer({ min: 1, max: 400 });

const subsystemNameArb = fc.constantFrom('fan', 'lpc', 'hpc', 'hpt', 'lpt', 'combustor');
const classificationArb = fc.constantFrom('nominal', 'degraded', 'critical');

const snapshotSubsystemArb = fc.record({
  name: subsystemNameArb,
  health_score: fc.double({ min: 0.0, max: 1.0, noNaN: true }),
  classification: classificationArb,
  is_incomplete: fc.boolean(),
});

const trajectoryPointArb = fc.record({
  cycle: cycleNumberArb,
  health_index: fc.double({ min: 0.0, max: 1.0, noNaN: true }),
});

const engineSnapshotArb: fc.Arbitrary<EngineSnapshot> = fc.record({
  engine_id: engineIdArb,
  rul: fc.record({
    engine_id: engineIdArb,
    current_rul: fc.integer({ min: 0, max: 125 }),
    cycle_count: fc.integer({ min: 0, max: 400 }),
    baseline_established: fc.boolean(),
    last_update_cycle: cycleNumberArb,
    is_incomplete: fc.boolean(),
  }),
  health: fc.record({
    engine_id: engineIdArb,
    health_index: fc.double({ min: 0.0, max: 1.0, noNaN: true }),
    cycle_count: fc.integer({ min: 0, max: 400 }),
    is_provisional: fc.boolean(),
    last_update_cycle: cycleNumberArb,
  }),
  subsystems: fc.array(snapshotSubsystemArb, { minLength: 1, maxLength: 6 }),
  trajectory: fc.array(trajectoryPointArb, { minLength: 0, maxLength: 50 }),
  degradation_rate: fc.oneof(
    fc.constant(null),
    fc.double({ min: -0.1, max: 0.1, noNaN: true })
  ),
}).map((snapshot) => ({
  // Ensure inner engine_id fields match the top-level engine_id for consistency
  ...snapshot,
  rul: { ...snapshot.rul, engine_id: snapshot.engine_id },
  health: { ...snapshot.health, engine_id: snapshot.engine_id },
}));

describe('Feature: digital-twin-experience, Property 25: Snapshot restore round-trip', () => {
  beforeEach(() => {
    useStore.setState({ engines: {}, selectedEngineId: null });
  });

  it('restoreSnapshot maps all snapshot fields to the correct engine state fields', () => {
    fc.assert(
      fc.property(engineSnapshotArb, (snapshot) => {
        useStore.setState({ engines: {} });

        useStore.getState().restoreSnapshot(snapshot);

        const engine = useStore.getState().engines[snapshot.engine_id];

        // Engine exists and has correct ID
        expect(engine).toBeDefined();
        expect(engine.engineId).toBe(snapshot.engine_id);

        // RUL fields mapped correctly
        expect(engine.rul).toBe(snapshot.rul.current_rul);
        expect(engine.isUrgent).toBe(snapshot.rul.current_rul < 30);

        // Health fields mapped correctly
        expect(engine.healthIndex).toBe(snapshot.health.health_index);
        expect(engine.isProvisional).toBe(snapshot.health.is_provisional);

        // Subsystems mapped correctly
        expect(engine.subsystems).toHaveLength(snapshot.subsystems.length);
        for (let i = 0; i < snapshot.subsystems.length; i++) {
          expect(engine.subsystems[i].name).toBe(snapshot.subsystems[i].name);
          expect(engine.subsystems[i].healthScore).toBe(snapshot.subsystems[i].health_score);
          expect(engine.subsystems[i].classification).toBe(snapshot.subsystems[i].classification);
        }

        // Trajectory mapped correctly
        expect(engine.trajectory).toHaveLength(snapshot.trajectory.length);
        for (let i = 0; i < snapshot.trajectory.length; i++) {
          expect(engine.trajectory[i].cycle).toBe(snapshot.trajectory[i].cycle);
          expect(engine.trajectory[i].healthIndex).toBe(snapshot.trajectory[i].health_index);
        }

        // Degradation rate preserved (including null)
        expect(engine.degradationRate).toBe(snapshot.degradation_rate);

        // lastUpdateCycle is max of rul and health last_update_cycle
        expect(engine.lastUpdateCycle).toBe(
          Math.max(snapshot.rul.last_update_cycle, snapshot.health.last_update_cycle)
        );
      }),
      { numRuns: 100 }
    );
  });

  it('restoreSnapshot preserves existing engines and only updates the target engine', () => {
    fc.assert(
      fc.property(
        engineSnapshotArb,
        fc.integer({ min: 101, max: 200 }), // Different engine ID range to avoid conflicts
        (snapshot, otherEngineId) => {
          // Pre-populate an engine that should not be affected
          useStore.setState({
            engines: {
              [otherEngineId]: {
                engineId: otherEngineId,
                rul: 100,
                healthIndex: 0.9,
                isProvisional: false,
                isUrgent: false,
                subsystems: [],
                trajectory: [],
                degradationRate: null,
                lastUpdateCycle: 50,
              },
            },
          });

          useStore.getState().restoreSnapshot(snapshot);

          const state = useStore.getState();

          // Other engine is untouched
          const other = state.engines[otherEngineId];
          expect(other).toBeDefined();
          expect(other.rul).toBe(100);
          expect(other.healthIndex).toBe(0.9);

          // Target engine is correctly restored
          const target = state.engines[snapshot.engine_id];
          expect(target).toBeDefined();
          expect(target.rul).toBe(snapshot.rul.current_rul);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('restoreSnapshot produces correct isUrgent flag based on RUL threshold', () => {
    fc.assert(
      fc.property(engineSnapshotArb, (snapshot) => {
        useStore.setState({ engines: {} });

        useStore.getState().restoreSnapshot(snapshot);

        const engine = useStore.getState().engines[snapshot.engine_id];

        // isUrgent should be derived from rul < 30
        if (snapshot.rul.current_rul < 30) {
          expect(engine.isUrgent).toBe(true);
        } else {
          expect(engine.isUrgent).toBe(false);
        }
      }),
      { numRuns: 100 }
    );
  });
});
