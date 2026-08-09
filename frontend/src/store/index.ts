import { create } from 'zustand';
import type {
  ChartDataPoint,
  SensorHealthState,
  SensorStatus,
  AnomalyAlert,
  PipelineHealthResponse,
  ConnectionState,
  ConnectionStatus,
  DataSourceId,
  CorrectionPayload,
} from '@/types';

const MAX_BUFFER_SIZE = 200;
const MAX_ANOMALIES = 100;
const ENSEMBLE_SPREAD_THRESHOLD = 0.5;

interface UIState {
  isLoading: boolean;
  error: string | null;
  isSwitchingSource: boolean;
}

interface StoreState {
  // Slices
  sensorData: Record<string, ChartDataPoint[]>;
  anomalies: AnomalyAlert[];
  sensorHealth: Record<string, SensorHealthState>;
  pipelineHealth: PipelineHealthResponse | null;
  connection: ConnectionState;
  activeSource: DataSourceId;
  ui: UIState;

  // Actions
  appendSensorData: (sensor_id: string, point: ChartDataPoint) => void;
  addAnomaly: (alert: AnomalyAlert) => void;
  updateSensorHealth: (sensor_id: string, correction: CorrectionPayload) => void;
  setPipelineHealth: (response: PipelineHealthResponse) => void;
  setConnectionState: (state: Partial<ConnectionState>) => void;
  setActiveSource: (source: DataSourceId) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setSwitchingSource: (switching: boolean) => void;
}

export function deriveSensorStatus(correction: CorrectionPayload): SensorStatus {
  if (correction.anomaly_flag) {
    return 'critical';
  }
  if (correction.ensemble_spread > ENSEMBLE_SPREAD_THRESHOLD) {
    return 'warning';
  }
  return 'healthy';
}

export const useStore = create<StoreState>((set) => ({
  // Initial state
  sensorData: {},
  anomalies: [],
  sensorHealth: {},
  pipelineHealth: null,
  connection: {
    status: 'disconnected' as ConnectionStatus,
    reconnectAttempts: 0,
    lastConnected: null,
    nextRetryMs: null,
  },
  activeSource: 'nasa-cmapss' as DataSourceId,
  ui: {
    isLoading: false,
    error: null,
    isSwitchingSource: false,
  },

  // Actions
  appendSensorData: (sensor_id, point) =>
    set((state) => {
      const existing = state.sensorData[sensor_id] ?? [];
      const updated =
        existing.length >= MAX_BUFFER_SIZE
          ? [...existing.slice(1), point]
          : [...existing, point];

      return {
        sensorData: {
          ...state.sensorData,
          [sensor_id]: updated,
        },
      };
    }),

  addAnomaly: (alert) =>
    set((state) => {
      const updated = [alert, ...state.anomalies];
      return {
        anomalies: updated.length > MAX_ANOMALIES ? updated.slice(0, MAX_ANOMALIES) : updated,
      };
    }),

  updateSensorHealth: (sensor_id, correction) =>
    set((state) => {
      const status = deriveSensorStatus(correction);
      const healthEntry: SensorHealthState = {
        sensor_id,
        status,
        lastUpdate: Date.now(),
      };

      return {
        sensorHealth: {
          ...state.sensorHealth,
          [sensor_id]: healthEntry,
        },
      };
    }),

  setPipelineHealth: (response) =>
    set(() => ({
      pipelineHealth: response,
    })),

  setConnectionState: (partial) =>
    set((state) => ({
      connection: {
        ...state.connection,
        ...partial,
      },
    })),

  setActiveSource: (source) =>
    set(() => ({
      activeSource: source,
    })),

  setLoading: (loading) =>
    set((state) => ({
      ui: { ...state.ui, isLoading: loading },
    })),

  setError: (error) =>
    set((state) => ({
      ui: { ...state.ui, error },
    })),

  setSwitchingSource: (switching) =>
    set((state) => ({
      ui: { ...state.ui, isSwitchingSource: switching },
    })),
}));

export type { StoreState, UIState };
export { MAX_BUFFER_SIZE, MAX_ANOMALIES, ENSEMBLE_SPREAD_THRESHOLD };
