import type { StateCreator } from 'zustand';
import type {
  CorrectionDataPoint,
  CorrectionMetricsState,
  CorrectionMetricsActions,
  ExtendedCorrectionPayload,
} from '@/types/correction-metrics';

const MAX_CORRECTION_HISTORY = 100;

export type CorrectionMetricsSlice = CorrectionMetricsState & CorrectionMetricsActions;

export const createCorrectionMetricsSlice: StateCreator<CorrectionMetricsSlice> = (set) => ({
  // Initial state
  correctionHistory: {},
  latestKalmanGain: {},
  latestInnovation: {},
  latestConfidenceBand: {},
  latestRawPrediction: {},

  // Actions
  updateCorrectionMetrics: (payload: ExtendedCorrectionPayload) =>
    set((state) => {
      const { sensor_id, timestamp, values, ensemble_spread } = payload;

      // Handle missing v1.2 fields gracefully — use null when absent
      const kalman_gain: number | null = payload.kalman_gain ?? null;
      const innovation_magnitude: number | null = payload.innovation_magnitude ?? null;
      const confidence_band_95: [number, number] | null = payload.confidence_band_95 ?? null;
      const raw_prediction: number | null = payload.raw_prediction ?? null;

      // Build the new data point
      const dataPoint: CorrectionDataPoint = {
        timestamp: new Date(timestamp).getTime(),
        kalman_gain,
        innovation_magnitude,
        confidence_band_95,
        raw_prediction,
        corrected_value: values[0],
        ensemble_spread,
      };

      // Get existing history for this sensor, apply FIFO eviction at max 100
      const existing = state.correctionHistory[sensor_id] ?? [];
      const updated =
        existing.length >= MAX_CORRECTION_HISTORY
          ? [...existing.slice(1), dataPoint]
          : [...existing, dataPoint];

      return {
        correctionHistory: {
          ...state.correctionHistory,
          [sensor_id]: updated,
        },
        latestKalmanGain: {
          ...state.latestKalmanGain,
          [sensor_id]: kalman_gain,
        },
        latestInnovation: {
          ...state.latestInnovation,
          [sensor_id]: innovation_magnitude,
        },
        latestConfidenceBand: {
          ...state.latestConfidenceBand,
          [sensor_id]: confidence_band_95,
        },
        latestRawPrediction: {
          ...state.latestRawPrediction,
          [sensor_id]: raw_prediction,
        },
      };
    }),
});

export { MAX_CORRECTION_HISTORY };
