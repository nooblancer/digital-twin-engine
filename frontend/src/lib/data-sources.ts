import type { DataSource } from '@/types';

export const DATA_SOURCES: DataSource[] = [
  { id: 'nasa-cmapss', label: 'NASA C-MAPSS', domain: 'Industrial' },
  { id: 'usgs-water', label: 'USGS Water', domain: 'Environmental' },
  { id: 'opensky-network', label: 'OpenSky Network', domain: 'Aviation' },
  { id: 'open-meteo', label: 'Open-Meteo', domain: 'Environmental' },
  { id: 'openweathermap', label: 'OpenWeatherMap', domain: 'Environmental' },
  { id: 'airship-rtds', label: 'Airship RTDS', domain: 'IoT' },
  { id: 'thingsboard', label: 'ThingsBoard', domain: 'IoT' },
  { id: 'adafruit-io', label: 'Adafruit IO', domain: 'IoT' },
  { id: 'eltrothings', label: 'ElthroThings', domain: 'IoT' },
  { id: 'crypto-websocket', label: 'Crypto WebSocket', domain: 'Financial' },
  { id: 'nasa-cmapss-extended', label: 'NASA C-MAPSS Extended', domain: 'Industrial' },
];
