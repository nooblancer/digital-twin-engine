// --- API Response Types ---

export interface SensorContribution {
  sensor_name: string;
  innovation_magnitude: number;
  sigma_deviation: number;
}

export interface AnomalyAnalysisResponse {
  engine_id: number;
  anomaly_active: boolean;
  timestamp: string | null;
  contributions: SensorContribution[];
}

export type AlertSeverity = 'low' | 'medium' | 'critical';

export interface MaintenanceRecommendation {
  severity: AlertSeverity;
  time_to_critical_cycles: number;
  confidence_score: number;
  suggested_action: string;
  predicted_failure_mode: string | null;
}

export interface MaintenanceRecommendationsResponse {
  engine_id: number;
  recommendations: MaintenanceRecommendation[];
}

export interface BenchmarkMetrics {
  raw_rmse: number;
  corrected_rmse: number;
  raw_mae: number;
  corrected_mae: number;
  correction_gain_pct: number;
  confidence_coverage_pct: number;
  sample_count: number;
}

export interface LatencyMetrics {
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
  sample_count: number;
}

export interface ThroughputMetrics {
  events_per_second: number;
  predictions_per_second: number;
  corrections_per_second: number;
}

export interface PerformanceMetrics {
  latency: LatencyMetrics;
  throughput: ThroughputMetrics;
}

// --- Predictive Alert ---

export interface PredictiveAlert {
  id: string;
  engineId: number;
  severity: AlertSeverity;
  timeToCriticalCycles: number;
  confidenceScore: number;
  suggestedAction: string;
  timestamp: number;
}

// --- Zustand Store Slice ---

export interface MissionControlState {
  // Alert state
  predictiveAlerts: PredictiveAlert[];
  addPredictiveAlert: (alert: PredictiveAlert) => void;
  dismissAlert: (alertId: string) => void;

  // Anomaly analysis state
  anomalyAnalysis: Record<number, AnomalyAnalysisResponse>; // engineId -> analysis
  setAnomalyAnalysis: (engineId: number, analysis: AnomalyAnalysisResponse) => void;

  // Performance metrics state
  performanceMetrics: PerformanceMetrics | null;
  setPerformanceMetrics: (metrics: PerformanceMetrics) => void;

  // Benchmark state
  benchmarkMetrics: BenchmarkMetrics | null;
  setBenchmarkMetrics: (metrics: BenchmarkMetrics) => void;

  // Event counter
  totalEventCount: number;
  incrementEventCount: () => void;
}
