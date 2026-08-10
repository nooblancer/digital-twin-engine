/**
 * Digital Twin types for turbofan engine prognostics.
 * Defines WebSocket message payloads, engine state, and store interfaces.
 */

// --- WebSocket Message Payloads ---

export interface RULUpdatePayload {
  engine_id: number;
  rul_cycles: number; // 0-125
  cycle_number: number;
  is_urgent: boolean; // true when rul < 30
}

export interface HealthIndexUpdatePayload {
  engine_id: number;
  health_index: number; // 0.0-1.0
  cycle_number: number;
  is_provisional: boolean; // true when < 10 cycles baseline
}

export interface SubsystemHealthUpdatePayload {
  engine_id: number;
  cycle_number: number;
  subsystems: {
    name: string; // fan, lpc, hpc, hpt, lpt, combustor
    health_score: number; // 0.0-1.0
    classification: string; // nominal, degraded, critical
  }[];
}

export interface DegradationUpdatePayload {
  engine_id: number;
  degradation_rate: number | null; // null if < 20 cycles
  cycle_number: number;
}

// --- Engine Snapshot (for WebSocket reconnection) ---

export interface EngineSnapshot {
  engine_id: number;
  rul: {
    engine_id: number;
    current_rul: number;
    cycle_count: number;
    baseline_established: boolean;
    last_update_cycle: number;
    is_incomplete: boolean;
  };
  health: {
    engine_id: number;
    health_index: number;
    cycle_count: number;
    is_provisional: boolean;
    last_update_cycle: number;
  };
  subsystems: {
    name: string;
    health_score: number;
    classification: string;
    is_incomplete: boolean;
  }[];
  trajectory: { cycle: number; health_index: number }[];
  degradation_rate: number | null;
}

// --- Frontend State ---

export interface SubsystemState {
  name: string;
  healthScore: number;
  classification: 'nominal' | 'degraded' | 'critical' | 'unknown';
}

export interface EngineState {
  engineId: number;
  rul: number;
  healthIndex: number;
  isProvisional: boolean;
  isUrgent: boolean;
  subsystems: SubsystemState[];
  trajectory: { cycle: number; healthIndex: number }[];
  degradationRate: number | null;
  lastUpdateCycle: number;
}

export interface DigitalTwinState {
  engines: Record<number, EngineState>;
  selectedEngineId: number | null;
  updateRUL: (payload: RULUpdatePayload) => void;
  updateHealthIndex: (payload: HealthIndexUpdatePayload) => void;
  updateSubsystemHealth: (payload: SubsystemHealthUpdatePayload) => void;
  updateDegradation: (payload: DegradationUpdatePayload) => void;
  selectEngine: (engineId: number) => void;
  restoreSnapshot: (snapshot: EngineSnapshot) => void;
}
