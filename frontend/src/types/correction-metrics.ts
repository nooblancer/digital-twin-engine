/**
 * Correction metrics types for EnKF observability.
 * Defines interfaces for Kalman Gain, innovation, confidence bands,
 * and raw prediction data flowing from the WebSocket correction payload
 * into the Zustand store and visualization components.
 */

/**
 * A single time-series data point for correction history charts.
 * Stored per-sensor in the Zustand correction metrics slice.
 */
export interface CorrectionDataPoint {
  timestamp: number;
  kalman_gain: number | null;
  innovation_magnitude: number | null;
  confidence_band_95: [number, number] | null;
  raw_prediction: number | null;
  corrected_value: number;
  ensemble_spread: number;
}

/**
 * State shape for the correction metrics Zustand slice.
 * Maintains per-sensor time-series history (max 100 points)
 * and latest values for gauge/indicator components.
 */
export interface CorrectionMetricsState {
  /** Per-sensor time-series history for charts (max 100 points) */
  correctionHistory: Record<string, CorrectionDataPoint[]>;
  /** Latest kalman gain values for KalmanGainIndicator */
  latestKalmanGain: Record<string, number | null>;
  /** Latest innovation magnitude values for InnovationMeter */
  latestInnovation: Record<string, number | null>;
  /** Latest confidence band values for ConfidenceBandChart */
  latestConfidenceBand: Record<string, [number, number] | null>;
  /** Latest raw prediction values for PredictionComparison */
  latestRawPrediction: Record<string, number | null>;
}

/**
 * Actions available on the correction metrics slice.
 */
export interface CorrectionMetricsActions {
  updateCorrectionMetrics: (payload: ExtendedCorrectionPayload) => void;
}

/**
 * Extended correction payload received from WebSocket.
 * Extends the base CorrectionPayload with v1.2 fields.
 * Optional/nullable new fields allow graceful handling of older messages.
 */
export interface ExtendedCorrectionPayload {
  sensor_id: string;
  timestamp: string;
  values: number[];
  ensemble_spread: number;
  anomaly_flag: boolean;
  kalman_gain?: number | null;
  innovation_magnitude?: number | null;
  confidence_band_95?: [number, number] | null;
  raw_prediction?: number | null;
}
