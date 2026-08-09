export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'reconnecting';

export interface ConnectionState {
  status: ConnectionStatus;
  reconnectAttempts: number;
  lastConnected: number | null;
  nextRetryMs: number | null;
}
