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
  DigitalTwinState,
} from '@/types';
import { createDigitalTwinSlice } from './digital-twin';
import { createCorrectionMetricsSlice, type CorrectionMetricsSlice } from './correction-metrics';
import { createMissionControlSlice, type MissionControlSlice } from './mission-control';
import { createFleetSlice, type FleetSlice } from './fleet-slice';

const MAX_BUFFER_SIZE = 200;
const MAX_ANOMALIES = 100;
const ENSEMBLE_SPREAD_THRESHOLD = 0.5;

interface UIState {
  isLoading: boolean;
  error: string | null;
  isSwitchingSource: boolean;
}

interface StoreState extends DigitalTwinState, CorrectionMetricsSlice, MissionControlSlice, FleetSlice {
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

export const useStore = create<StoreState>((set, get, store) => ({
  // Digital Twin slice
  ...createDigitalTwinSlice(set, get, store),

  // Correction Metrics slice
  ...createCorrectionMetricsSlice(set, get, store),

  // Mission Control slice
  ...createMissionControlSlice(set, get, store),

  // Fleet slice
  ...createFleetSlice(set, get, store),

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
      
      // Try to merge with the last entry if timestamps are close (within 2 seconds)
      const MERGE_THRESHOLD_MS = 2000;
      const lastIdx = existing.length - 1;
      
      if (lastIdx >= 0 && Math.abs(existing[lastIdx].timestamp - point.timestamp) < MERGE_THRESHOLD_MS) {
        // Merge into existing entry
        const merged = { ...existing[lastIdx], ...point };
        const updated = [...existing.slice(0, lastIdx), merged];
        return {
          sensorData: {
            ...state.sensorData,
            [sensor_id]: updated,
          },
        };
      }
      
      // Also check second-to-last (predictions sometimes arrive slightly after corrections)
      if (lastIdx >= 1 && Math.abs(existing[lastIdx - 1].timestamp - point.timestamp) < MERGE_THRESHOLD_MS) {
        const merged = { ...existing[lastIdx - 1], ...point };
        const updated = [...existing.slice(0, lastIdx - 1), merged, existing[lastIdx]];
        return {
          sensorData: {
            ...state.sensorData,
            [sensor_id]: updated,
          },
        };
      }
      
      // Otherwise append as new entry
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
