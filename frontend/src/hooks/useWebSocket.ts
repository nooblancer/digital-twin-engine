'use client';

import { useEffect, useRef, useCallback } from 'react';
import { useStore } from '@/store';
import { computeBackoffDelay } from '@/lib/websocket-utils';
import type {
  WebSocketMessage,
  TelemetryPayload,
  PredictionPayload,
  CorrectionPayload,
  AnomalyPayload,
} from '@/types';

const DEFAULT_WS_URL =
  process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws/telemetry';

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

/**
 * Hook that manages a persistent WebSocket connection to the telemetry
 * endpoint with exponential backoff reconnection.
 *
 * Dispatches incoming messages to the Zustand store based on `type` field.
 */
export function useWebSocket(url: string = DEFAULT_WS_URL): void {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptsRef = useRef(0);
  const unmountedRef = useRef(false);

  const appendSensorData = useStore((s) => s.appendSensorData);
  const addAnomaly = useStore((s) => s.addAnomaly);
  const updateSensorHealth = useStore((s) => s.updateSensorHealth);
  const setConnectionState = useStore((s) => s.setConnectionState);

  const handleMessage = useCallback(
    (event: MessageEvent) => {
      let message: WebSocketMessage;

      try {
        message = JSON.parse(event.data);
      } catch {
        console.warn('[useWebSocket] Malformed JSON message received:', event.data);
        return;
      }

      if (!message || typeof message.type !== 'string' || !message.payload) {
        console.warn('[useWebSocket] Invalid message structure:', message);
        return;
      }

      switch (message.type) {
        case 'telemetry': {
          const payload = message.payload as TelemetryPayload;
          appendSensorData(payload.sensor_id, {
            timestamp: new Date(payload.timestamp).getTime(),
            raw: payload.value,
          });
          break;
        }
        case 'prediction': {
          const payload = message.payload as PredictionPayload;
          appendSensorData(payload.sensor_id, {
            timestamp: new Date(payload.prediction_timestamp).getTime(),
            predicted: payload.state_vector[0],
          });
          break;
        }
        case 'correction': {
          const payload = message.payload as CorrectionPayload;
          appendSensorData(payload.sensor_id, {
            timestamp: new Date(payload.timestamp).getTime(),
            corrected: payload.values[0],
          });
          updateSensorHealth(payload.sensor_id, payload);
          break;
        }
        case 'anomaly': {
          const payload = message.payload as AnomalyPayload;
          addAnomaly({
            id: generateId(),
            sensor_id: payload.sensor_id,
            timestamp: payload.timestamp,
            severity: payload.severity,
            description: payload.description,
          });
          break;
        }
        default:
          console.warn('[useWebSocket] Unknown message type:', message.type);
      }
    },
    [appendSensorData, addAnomaly, updateSensorHealth]
  );

  const connect = useCallback(() => {
    if (unmountedRef.current) return;

    setConnectionState({ status: attemptsRef.current === 0 ? 'connecting' : 'reconnecting' });

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (unmountedRef.current) {
        ws.close();
        return;
      }
      attemptsRef.current = 0;
      setConnectionState({
        status: 'connected',
        reconnectAttempts: 0,
        lastConnected: Date.now(),
        nextRetryMs: null,
      });
    };

    ws.onmessage = handleMessage;

    ws.onclose = () => {
      if (unmountedRef.current) return;

      attemptsRef.current += 1;
      const delay = computeBackoffDelay(attemptsRef.current);

      setConnectionState({
        status: 'disconnected',
        reconnectAttempts: attemptsRef.current,
        nextRetryMs: delay,
      });

      reconnectTimeoutRef.current = setTimeout(() => {
        if (!unmountedRef.current) {
          connect();
        }
      }, delay);
    };

    ws.onerror = () => {
      // The onerror event is always followed by onclose, so reconnection
      // logic is handled there. We just log for debugging.
      if (!unmountedRef.current) {
        console.warn('[useWebSocket] Connection error');
      }
    };
  }, [url, handleMessage, setConnectionState]);

  useEffect(() => {
    unmountedRef.current = false;
    connect();

    return () => {
      unmountedRef.current = true;

      if (reconnectTimeoutRef.current !== null) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }

      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }

      setConnectionState({ status: 'disconnected', nextRetryMs: null });
    };
  }, [connect, setConnectionState]);
}

export default useWebSocket;
export { computeBackoffDelay } from '@/lib/websocket-utils';
