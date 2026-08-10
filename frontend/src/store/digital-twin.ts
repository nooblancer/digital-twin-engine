import type { StateCreator } from 'zustand';
import type {
  DigitalTwinState,
  EngineState,
  SubsystemState,
  RULUpdatePayload,
  HealthIndexUpdatePayload,
  SubsystemHealthUpdatePayload,
  DegradationUpdatePayload,
  EngineSnapshot,
} from '@/types/digital-twin';

function createDefaultEngineState(engineId: number): EngineState {
  return {
    engineId,
    rul: 125,
    healthIndex: 1.0,
    isProvisional: true,
    isUrgent: false,
    subsystems: [],
    trajectory: [],
    degradationRate: null,
    lastUpdateCycle: 0,
  };
}

function getOrCreateEngine(
  engines: Record<number, EngineState>,
  engineId: number
): EngineState {
  return engines[engineId] ?? createDefaultEngineState(engineId);
}

export const createDigitalTwinSlice: StateCreator<DigitalTwinState> = (set) => ({
  engines: {},
  selectedEngineId: null,

  updateRUL: (payload: RULUpdatePayload) =>
    set((state) => {
      const engine = getOrCreateEngine(state.engines, payload.engine_id);
      const updated: EngineState = {
        ...engine,
        rul: payload.rul_cycles,
        isUrgent: payload.is_urgent,
        lastUpdateCycle: payload.cycle_number,
      };
      return {
        engines: { ...state.engines, [payload.engine_id]: updated },
      };
    }),

  updateHealthIndex: (payload: HealthIndexUpdatePayload) =>
    set((state) => {
      const engine = getOrCreateEngine(state.engines, payload.engine_id);
      const updated: EngineState = {
        ...engine,
        healthIndex: payload.health_index,
        isProvisional: payload.is_provisional,
        lastUpdateCycle: payload.cycle_number,
      };
      return {
        engines: { ...state.engines, [payload.engine_id]: updated },
      };
    }),

  updateSubsystemHealth: (payload: SubsystemHealthUpdatePayload) =>
    set((state) => {
      const engine = getOrCreateEngine(state.engines, payload.engine_id);
      const subsystems: SubsystemState[] = payload.subsystems.map((s) => ({
        name: s.name,
        healthScore: s.health_score,
        classification: s.classification as SubsystemState['classification'],
      }));
      const updated: EngineState = {
        ...engine,
        subsystems,
        lastUpdateCycle: payload.cycle_number,
      };
      return {
        engines: { ...state.engines, [payload.engine_id]: updated },
      };
    }),

  updateDegradation: (payload: DegradationUpdatePayload) =>
    set((state) => {
      const engine = getOrCreateEngine(state.engines, payload.engine_id);
      const updated: EngineState = {
        ...engine,
        degradationRate: payload.degradation_rate,
        lastUpdateCycle: payload.cycle_number,
      };
      return {
        engines: { ...state.engines, [payload.engine_id]: updated },
      };
    }),

  selectEngine: (engineId: number) =>
    set(() => ({
      selectedEngineId: engineId,
    })),

  restoreSnapshot: (snapshot: EngineSnapshot) =>
    set((state) => {
      const subsystems: SubsystemState[] = snapshot.subsystems.map((s) => ({
        name: s.name,
        healthScore: s.health_score,
        classification: s.classification as SubsystemState['classification'],
      }));

      const trajectory = snapshot.trajectory.map((t) => ({
        cycle: t.cycle,
        healthIndex: t.health_index,
      }));

      const engineState: EngineState = {
        engineId: snapshot.engine_id,
        rul: snapshot.rul.current_rul,
        healthIndex: snapshot.health.health_index,
        isProvisional: snapshot.health.is_provisional,
        isUrgent: snapshot.rul.current_rul < 30,
        subsystems,
        trajectory,
        degradationRate: snapshot.degradation_rate,
        lastUpdateCycle: Math.max(
          snapshot.rul.last_update_cycle,
          snapshot.health.last_update_cycle
        ),
      };

      return {
        engines: { ...state.engines, [snapshot.engine_id]: engineState },
      };
    }),
});

export { createDefaultEngineState, getOrCreateEngine };
