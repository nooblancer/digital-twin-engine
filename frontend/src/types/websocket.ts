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

export interface WebSocketMessage {
  type: 'telemetry' | 'prediction' | 'correction' | 'anomaly';
  payload: TelemetryPayload | PredictionPayload | CorrectionPayload | AnomalyPayload;
}
