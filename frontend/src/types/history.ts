export interface HistoryQueryParams {
  sensor_id: string;
  start: string; // ISO 8601
  end: string; // ISO 8601
  limit: number;
  offset: number;
}

export interface PredictionEntry {
  timestamp: string;
  state_vector: number[];
  model_used: string;
  prediction_horizon_seconds: number;
}
