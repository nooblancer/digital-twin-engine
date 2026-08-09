export interface AnomalyAlert {
  id: string;
  sensor_id: string;
  timestamp: string;
  severity: 'informational' | 'warning' | 'critical';
  description: string;
}
