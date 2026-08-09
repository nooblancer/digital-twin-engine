export interface ChartDataPoint {
  timestamp: number; // Unix ms
  raw?: number;
  predicted?: number;
  corrected?: number;
}

export type SensorStatus = 'healthy' | 'warning' | 'critical';

export interface SensorHealthState {
  sensor_id: string;
  status: SensorStatus;
  lastUpdate: number; // Unix ms
}
