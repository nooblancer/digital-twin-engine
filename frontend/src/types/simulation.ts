/**
 * Simulation types for fault injection and what-if scenario APIs.
 * Defines interfaces matching the backend API response schemas for:
 * - Monte Carlo forward projection results
 * - Active fault injection state
 * - Maintenance impact analysis
 * - Failure probability cache data
 * - Fault injection request parameters
 */

/**
 * Result of a what-if simulation from POST /simulation/what-if.
 * Contains trajectory percentiles from Monte Carlo projection,
 * failure probability curve, and RUL statistics.
 */
export interface SimulationResult {
  percentiles: {
    5: number[];
    25: number[];
    50: number[];
    75: number[];
    95: number[];
  };
  failure_probability_by_cycle: number[];
  expected_rul: number | null;
  confidence_interval_90: [number, number] | null;
}

/**
 * An active fault injection as returned by GET /sensors/active-faults.
 * Represents a currently running sensor fault with remaining duration.
 */
export interface ActiveFault {
  injection_id: string;
  sensor_id: string;
  fault_type: 'spike' | 'drift' | 'dropout' | 'noise';
  magnitude: number;
  remaining_cycles: number;
  start_cycle: number;
}

/**
 * Result of POST /simulation/maintenance-impact.
 * Compares RUL and trajectory percentiles before and after
 * a simulated maintenance intervention.
 */
export interface MaintenanceImpactResult {
  before_rul: number | null;
  after_rul: number | null;
  trajectory_percentiles_before: Record<number, number[]>;
  trajectory_percentiles_after: Record<number, number[]>;
}

/**
 * Cached failure probability data from GET /engines/{id}/failure-probability.
 * Precomputed by the background cache task every 30 seconds.
 */
export interface FailureProbabilityResult {
  engine_id: number;
  failure_probability_by_cycle: number[];
  expected_rul: number | null;
  confidence_interval_90: [number, number] | null;
  computed_at: string;
}

/**
 * Parameters for POST /sensors/inject-fault request body.
 */
export interface InjectFaultParams {
  sensor_id: string;
  fault_type: 'spike' | 'drift' | 'dropout' | 'noise';
  magnitude: number;
  duration_cycles: number;
}
