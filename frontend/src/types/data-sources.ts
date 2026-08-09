export type DataSourceId =
  | 'nasa-cmapss'
  | 'usgs-water'
  | 'opensky-network'
  | 'open-meteo'
  | 'openweathermap'
  | 'airship-rtds'
  | 'thingsboard'
  | 'adafruit-io'
  | 'eltrothings'
  | 'crypto-websocket'
  | 'nasa-cmapss-extended';

export interface DataSource {
  id: DataSourceId;
  label: string;
  domain: 'Industrial' | 'Environmental' | 'Aviation' | 'IoT' | 'Behavioral' | 'Financial';
}
