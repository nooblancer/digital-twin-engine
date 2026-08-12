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
  RULUpdatePayload,
  HealthIndexUpdatePayload,
  SubsystemHealthUpdatePayload,
  DegradationUpdatePayload,
  EngineSnapshot,
} from '@/types';
import type { ExtendedCorrectionPayload } from '@/types/correction-metrics';

const DEFAULT_WS_URL =
  process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws/telemetry';

const DEFAULT_API_BASE =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

/**
 * Fetches the latest engine snapshot from the REST API.
 * Used on WebSocket reconnection to restore display state without full data replay.
 */
async function fetchEngineSnapshot(
  apiBase: string,
  engineId: number
): Promise<EngineSnapshot | null> {
  try {
    const response = await fetch(`${apiBase}/api/engines/${engineId}/snapshot`);
    if (!response.ok) {
      console.warn(
        `[useWebSocket] Snapshot fetch failed for engine ${engineId}: ${response.status}`
      );
      return null;
    }
    return (await response.json()) as EngineSnapshot;
  } catch (error) {
    console.warn(`[useWebSocket] Snapshot fetch error for engine ${engineId}:`, error);
    return null;
  }
}

/**
 * Hook that manages a persistent WebSocket connection to the telemetry
 * endpoint with exponential backoff reconnection.
 *
 * Dispatches incoming messages to the Zustand store based on `type` field.
 * On reconnection, requests the latest engine snapshot(s) to restore state.
 */
export function useWebSocket(url: string = DEFAULT_WS_URL): void {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptsRef = useRef(0);
  const unmountedRef = useRef(false);
  const hasConnectedBefore = useRef(false);

  const appendSensorData = useStore((s) => s.appendSensorData);
  const addAnomaly = useStore((s) => s.addAnomaly);
  const updateSensorHealth = useStore((s) => s.updateSensorHealth);
  const setConnectionState = useStore((s) => s.setConnectionState);
  const updateRUL = useStore((s) => s.updateRUL);
  const updateHealthIndex = useStore((s) => s.updateHealthIndex);
  const updateSubsystemHealth = useStore((s) => s.updateSubsystemHealth);
  const updateDegradation = useStore((s) => s.updateDegradation);
  const restoreSnapshot = useStore((s) => s.restoreSnapshot);
  const updateCorrectionMetrics = useStore((s) => s.updateCorrectionMetrics);
  const incrementEventCount = useStore((s) => s.incrementEventCount);

  const requestSnapshotsOnReconnect = useCallback(async () => {
    const state = useStore.getState();
    const engineIds = Object.keys(state.engines).map(Number);

    if (engineIds.length === 0) return;

    const snapshotPromises = engineIds.map((engineId) =>
      fetchEngineSnapshot(DEFAULT_API_BASE, engineId)
    );

    const snapshots = await Promise.all(snapshotPromises);

    for (const snapshot of snapshots) {
      if (snapshot && !unmountedRef.current) {
        restoreSnapshot(snapshot);
      }
    }
  }, [restoreSnapshot]);

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
          incrementEventCount();
          break;
        }
        case 'prediction': {
          const payload = message.payload as PredictionPayload;
          appendSensorData(payload.sensor_id, {
            timestamp: new Date(payload.prediction_timestamp).getTime(),
            predicted: payload.state_vector[0],
          });
          incrementEventCount();
          break;
        }
        case 'correction': {
          const payload = message.payload as CorrectionPayload;
          appendSensorData(payload.sensor_id, {
            timestamp: new Date(payload.timestamp).getTime(),
            corrected: payload.values[0],
          });
          updateSensorHealth(payload.sensor_id, payload);
          updateCorrectionMetrics(message.payload as ExtendedCorrectionPayload);
          incrementEventCount();
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
          incrementEventCount();
          break;
        }
        case 'rul_update': {
          const payload = message.payload as RULUpdatePayload;
          updateRUL(payload);
          incrementEventCount();
          break;
        }
        case 'health_index_update': {
          const payload = message.payload as HealthIndexUpdatePayload;
          updateHealthIndex(payload);
          incrementEventCount();
          break;
        }
        case 'subsystem_health_update': {
          const payload = message.payload as SubsystemHealthUpdatePayload;
          updateSubsystemHealth(payload);
          incrementEventCount();
          break;
        }
        case 'degradation_update': {
          const payload = message.payload as DegradationUpdatePayload;
          updateDegradation(payload);
          incrementEventCount();
          break;
        }
        default:
          console.warn('[useWebSocket] Unknown message type:', (message as { type: string }).type);
      }
    },
    [
      appendSensorData,
      addAnomaly,
      updateSensorHealth,
      updateRUL,
      updateHealthIndex,
      updateSubsystemHealth,
      updateDegradation,
      updateCorrectionMetrics,
      incrementEventCount,
    ]
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

      const isReconnection = hasConnectedBefore.current;
      hasConnectedBefore.current = true;
      attemptsRef.current = 0;

      setConnectionState({
        status: 'connected',
        reconnectAttempts: 0,
        lastConnected: Date.now(),
        nextRetryMs: null,
      });

      // On reconnection, request snapshots to restore display state
      if (isReconnection) {
        requestSnapshotsOnReconnect();
      }
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
  }, [url, handleMessage, setConnectionState, requestSnapshotsOnReconnect]);

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
export { fetchEngineSnapshot };
