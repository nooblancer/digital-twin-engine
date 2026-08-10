import type {
  RULUpdatePayload,
  HealthIndexUpdatePayload,
  SubsystemHealthUpdatePayload,
  DegradationUpdatePayload,
} from './digital-twin';

export interface TelemetryPayload {
  sensor_id: string;
  timestamp: string;
  measurement_type: string;
  value: number;
}

export interface PredictionPayload {
  sensor_id: string;
  prediction_timestamp: string;
  state_vector: number[];
  model_used: string;
  prediction_horizon_seconds: number;
}

export interface CorrectionPayload {
  sensor_id: string;
  timestamp: string;
  values: number[];
  ensemble_spread: number;
  anomaly_flag: boolean;
}

export interface AnomalyPayload {
  sensor_id: string;
  timestamp: string;
  severity: 'informational' | 'warning' | 'critical';
  description: string;
}

export type MessageType =
  | 'telemetry'
  | 'prediction'
  | 'correction'
  | 'anomaly'
  | 'rul_update'
  | 'health_index_update'
  | 'subsystem_health_update'
  | 'degradation_update';

export interface WebSocketMessage {
  type: MessageType;
  payload:
    | TelemetryPayload
    | PredictionPayload
    | CorrectionPayload
    | AnomalyPayload
    | RULUpdatePayload
    | HealthIndexUpdatePayload
    | SubsystemHealthUpdatePayload
    | DegradationUpdatePayload;
}
