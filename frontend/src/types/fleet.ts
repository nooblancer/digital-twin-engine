// --- Fleet Pattern Types ---

export interface EnginePairSimilarity {
  engine_a: number;
  engine_b: number;
  similarity_score: number;
}

export interface PatternCluster {
  cluster_id: string;
  engine_ids: number[];
  pairwise_similarities: EnginePairSimilarity[];
  dominant_failure_mode: string;
}

export interface FleetPatternResponse {
  clusters: PatternCluster[];
  insufficient_data: number[];
  computed_at: string;
}

// --- Fleet Stats Types ---

export interface FleetStatsResponse {
  total_engines: number;
  nominal_count: number;
  degraded_count: number;
  critical_count: number;
  calibrating_count: number;
  average_fleet_health_index: number | null;
  predicted_maintenance_events: number;
  horizon_cycles: number;
}

// --- Maintenance Recommendation Types ---

export interface MaintenanceRecommendation {
  failure_mode: string;
  confidence: number;
  recommended_action: string;
  contributing_sensors: string[];
}

// --- Fleet Zustand Slice State ---

export interface FleetSliceState {
  patterns: FleetPatternResponse | null;
  stats: FleetStatsResponse | null;
  patternsLoading: boolean;
  statsLoading: boolean;
  patternsError: string | null;
  statsError: string | null;
  setFleetPatterns: (patterns: FleetPatternResponse) => void;
  setFleetStats: (stats: FleetStatsResponse) => void;
  setPatternsLoading: (loading: boolean) => void;
  setStatsLoading: (loading: boolean) => void;
  setPatternsError: (error: string | null) => void;
  setStatsError: (error: string | null) => void;
  clearFleetData: () => void;
}
