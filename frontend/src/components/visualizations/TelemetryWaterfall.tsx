'use client';

import { useRef, useEffect, useCallback, useState } from 'react';
import { useStore } from '@/store';

// --- Constants ---
const CELL_WIDTH = 12; // px per time step
const CELL_HEIGHT = 20; // px per channel
const VISIBLE_STEPS = 50;
const BUFFER_SIZE = VISIBLE_STEPS + 10; // Ring buffer size to avoid reallocation

/**
 * Default 21 C-MAPSS sensor channel names.
 * These correspond to the standard turbofan engine sensor suite.
 */
const DEFAULT_CHANNELS: string[] = [
  'Fan inlet temp (T2)',
  'LPC outlet temp (T24)',
  'HPC outlet temp (T30)',
  'LPT outlet temp (T50)',
  'Fan inlet pressure (P2)',
  'Bypass-duct pressure (P15)',
  'HPC outlet pressure (P30)',
  'Physical fan speed (Nf)',
  'Physical core speed (Nc)',
  'Engine pressure ratio (epr)',
  'HPC outlet static press (Ps30)',
  'Fuel/air ratio (phi)',
  'Corrected fan speed (NRf)',
  'Corrected core speed (NRc)',
  'Bypass ratio (BPR)',
  'Burner fuel-air ratio (farB)',
  'Bleed enthalpy (htBleed)',
  'Demanded fan speed (Nf_dmd)',
  'Demanded corrected fan speed (PCNfR_dmd)',
  'HPT coolant bleed (W31)',
  'LPT coolant bleed (W32)',
];

// --- Types ---
export interface WaterfallCell {
  sensorIndex: number; // 0-20
  timeStep: number;
  deviation: number; // Normalized 0.0 (baseline) to 1.0 (max deviation)
}

export interface TelemetryWaterfallProps {
  /** 21 sensor channel names */
  channels?: string[];
  /** Visible time steps, default 50 */
  visibleSteps?: number;
  /** Color scale selection */
  colorScale?: 'cyan' | 'thermal';
  /** Additional class names */
  className?: string;
}

/**
 * Ring buffer implementation to store waterfall column data without reallocation.
 * Each column is an array of 21 deviation values (one per sensor channel).
 */
export class WaterfallRingBuffer {
  private _buffer: (number[] | null)[];
  private _head: number = 0;
  private _size: number = 0;
  private _capacity: number;

  constructor(capacity: number) {
    this._capacity = capacity;
    this._buffer = new Array(capacity).fill(null);
  }

  get length(): number {
    return this._size;
  }

  get capacity(): number {
    return this._capacity;
  }

  /** Push a new column (array of deviations) to the buffer */
  push(column: number[]): void {
    const writeIndex = (this._head + this._size) % this._capacity;
    this._buffer[writeIndex] = column;
    if (this._size < this._capacity) {
      this._size++;
    } else {
      // Buffer full — advance head to evict oldest entry
      this._head = (this._head + 1) % this._capacity;
    }
  }

  /** Get item at logical index (0 = oldest still in buffer) */
  get(index: number): number[] | null {
    if (index < 0 || index >= this._size) return null;
    const actualIndex = (this._head + index) % this._capacity;
    return this._buffer[actualIndex];
  }

  /** Get the most recent N items as an array */
  getRecent(count: number): (number[] | null)[] {
    const start = Math.max(0, this._size - count);
    const result: (number[] | null)[] = [];
    for (let i = start; i < this._size; i++) {
      result.push(this.get(i));
    }
    return result;
  }

  /** Clear the buffer */
  clear(): void {
    this._buffer = new Array(this._capacity).fill(null);
    this._head = 0;
    this._size = 0;
  }
}

/**
 * Compute the fill color for a cell based on deviation value.
 * Low deviation = dim cyan: rgba(0, 212, 255, 0.1)
 * High deviation = bright cyan: rgba(0, 212, 255, 1.0)
 */
function getCellColor(deviation: number, colorScale: 'cyan' | 'thermal'): string {
  const clamped = Math.max(0, Math.min(1, deviation));
  if (colorScale === 'thermal') {
    // Thermal: blue → yellow → red
    if (clamped < 0.5) {
      const t = clamped * 2;
      const r = Math.round(255 * t);
      const g = Math.round(200 * t);
      return `rgba(${r}, ${g}, 100, ${0.1 + clamped * 0.9})`;
    } else {
      const t = (clamped - 0.5) * 2;
      const g = Math.round(200 * (1 - t));
      return `rgba(255, ${g}, 0, ${0.1 + clamped * 0.9})`;
    }
  }
  // Default cyan scale
  const alpha = 0.1 + clamped * 0.9;
  return `rgba(0, 212, 255, ${alpha})`;
}

/**
 * TelemetryWaterfall — Scrolling 21-channel heatmap showing sensor deviation
 * from baseline over time.
 *
 * Renders using HTML5 Canvas for 60fps performance (21 rows × 50 columns = 1050 cells).
 * Falls back to an HTML table if Canvas is unavailable.
 *
 * Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6
 */
export function TelemetryWaterfall({
  channels = DEFAULT_CHANNELS,
  visibleSteps = VISIBLE_STEPS,
  colorScale = 'cyan',
  className,
}: TelemetryWaterfallProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const bufferRef = useRef<WaterfallRingBuffer>(
    new WaterfallRingBuffer(BUFFER_SIZE)
  );
  const rafRef = useRef<number | null>(null);
  const [canvasSupported, setCanvasSupported] = useState(true);

  // Read sensor data from the Zustand store
  const sensorData = useStore((state) => state.sensorData);
  const lastDataRef = useRef<Record<string, number>>({});

  // Track the total number of time steps we've seen
  const timeStepCountRef = useRef(0);

  const channelCount = channels.length;
  const canvasWidth = visibleSteps * CELL_WIDTH;
  const canvasHeight = channelCount * CELL_HEIGHT;

  /**
   * Draw the entire waterfall grid to the canvas.
   */
  const drawWaterfall = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      setCanvasSupported(false);
      return;
    }

    // Clear canvas
    ctx.clearRect(0, 0, canvasWidth, canvasHeight);

    // Get the most recent visibleSteps columns from the ring buffer
    const columns = bufferRef.current.getRecent(visibleSteps);

    for (let col = 0; col < columns.length; col++) {
      const column = columns[col];
      if (!column) continue;
      for (let row = 0; row < channelCount; row++) {
        const deviation = column[row] ?? 0;
        ctx.fillStyle = getCellColor(deviation, colorScale);
        ctx.fillRect(
          col * CELL_WIDTH,
          row * CELL_HEIGHT,
          CELL_WIDTH - 1,
          CELL_HEIGHT - 1
        );
      }
    }
  }, [canvasWidth, canvasHeight, visibleSteps, channelCount, colorScale]);

  /**
   * Compute deviations from the current sensor data and push a new column
   * when new data arrives.
   */
  useEffect(() => {
    // Check for new data by looking at the latest corrected values for each sensor
    const sensorIds = Object.keys(sensorData);
    if (sensorIds.length === 0) return;

    // Build a column of deviation values for all 21 channels
    // Use simple heuristic: deviation = abs(latest corrected - first corrected) / range
    // If no data is available for a channel, use 0
    let hasNewData = false;

    const newColumn: number[] = new Array(channelCount).fill(0);

    for (let i = 0; i < channelCount; i++) {
      // Map channel index to a sensor_id from the store
      // Sensors in the store are keyed by sensor_id strings
      const sensorId = sensorIds[i];
      if (!sensorId) continue;

      const points = sensorData[sensorId];
      if (!points || points.length === 0) continue;

      const latestPoint = points[points.length - 1];
      const latestValue = latestPoint.corrected ?? latestPoint.predicted ?? latestPoint.raw ?? 0;

      // Compute deviation from baseline (first value as baseline)
      const baselinePoint = points[0];
      const baselineValue = baselinePoint.corrected ?? baselinePoint.predicted ?? baselinePoint.raw ?? 0;

      // Normalize deviation: use running range for scale
      let min = Infinity;
      let max = -Infinity;
      for (const p of points) {
        const v = p.corrected ?? p.predicted ?? p.raw ?? 0;
        if (v < min) min = v;
        if (v > max) max = v;
      }
      const range = max - min;

      let deviation = 0;
      if (range > 0) {
        deviation = Math.abs(latestValue - baselineValue) / range;
      }
      newColumn[i] = Math.max(0, Math.min(1, deviation));

      // Check if data changed
      if (lastDataRef.current[sensorId] !== latestValue) {
        hasNewData = true;
        lastDataRef.current[sensorId] = latestValue;
      }
    }

    if (hasNewData) {
      bufferRef.current.push(newColumn);
      timeStepCountRef.current++;
    }
  }, [sensorData, channelCount]);

  /**
   * requestAnimationFrame rendering loop for 60fps.
   */
  useEffect(() => {
    if (!canvasSupported) return;

    let running = true;

    const loop = () => {
      if (!running) return;
      drawWaterfall();
      rafRef.current = requestAnimationFrame(loop);
    };

    rafRef.current = requestAnimationFrame(loop);

    return () => {
      running = false;
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [canvasSupported, drawWaterfall]);

  /**
   * Check canvas support on mount.
   */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas) {
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        setCanvasSupported(false);
      }
    }
  }, []);

  // --- Fallback: HTML table if Canvas is not supported ---
  if (!canvasSupported) {
    const columns = bufferRef.current.getRecent(visibleSteps);
    return (
      <div className={className} role="grid" aria-label="Telemetry waterfall heatmap (fallback)">
        <table className="border-collapse text-xs">
          <thead>
            <tr>
              <th className="text-left text-muted-foreground px-1">Sensor</th>
              {Array.from({ length: Math.min(visibleSteps, columns.length) }, (_, i) => (
                <th key={i} className="px-0.5 text-muted-foreground">
                  {i + 1}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {channels.map((channel, rowIdx) => (
              <tr key={channel}>
                <td className="text-left text-muted-foreground px-1 whitespace-nowrap">
                  {channel}
                </td>
                {columns.map((col, colIdx) => {
                  const deviation = col ? col[rowIdx] ?? 0 : 0;
                  return (
                    <td
                      key={colIdx}
                      className="px-0"
                      style={{
                        width: `${CELL_WIDTH}px`,
                        height: `${CELL_HEIGHT}px`,
                        backgroundColor: getCellColor(deviation, colorScale),
                      }}
                    />
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  // --- Primary: Canvas rendering ---
  // Label width for the sensor names column
  const labelWidth = 160;

  return (
    <div
      className={`flex flex-col ${className ?? ''}`}
      role="img"
      aria-label="Telemetry waterfall heatmap showing 21 sensor channel deviations over time"
    >
      {/* Main content: labels + canvas */}
      <div className="flex">
        {/* Sensor labels (left column) */}
        <div
          className="flex flex-col flex-shrink-0"
          style={{ width: `${labelWidth}px` }}
        >
          {channels.map((channel) => (
            <div
              key={channel}
              className="text-[10px] text-muted-foreground truncate flex items-center"
              style={{ height: `${CELL_HEIGHT}px` }}
              title={channel}
            >
              {channel}
            </div>
          ))}
        </div>

        {/* Canvas heatmap */}
        <div className="overflow-hidden" style={{ width: canvasWidth, height: canvasHeight }}>
          <canvas
            ref={canvasRef}
            width={canvasWidth}
            height={canvasHeight}
            className="block"
            data-testid="waterfall-canvas"
          />
        </div>
      </div>

      {/* Color legend */}
      <div className="flex items-center gap-2 mt-2 ml-auto mr-0" style={{ paddingLeft: `${labelWidth}px` }}>
        <span className="text-[10px] text-muted-foreground">Low</span>
        <div
          className="h-3 rounded-sm"
          style={{
            width: '120px',
            background:
              colorScale === 'cyan'
                ? 'linear-gradient(to right, rgba(0, 212, 255, 0.1), rgba(0, 212, 255, 1.0))'
                : 'linear-gradient(to right, rgba(0, 100, 255, 0.3), rgba(255, 200, 0, 0.8), rgba(255, 0, 0, 1.0))',
          }}
        />
        <span className="text-[10px] text-muted-foreground">High</span>
        <span className="text-[10px] text-muted-foreground ml-2">Deviation</span>
      </div>
    </div>
  );
}

// Export constants and buffer class for testing
export { CELL_WIDTH, CELL_HEIGHT, VISIBLE_STEPS, BUFFER_SIZE, DEFAULT_CHANNELS, getCellColor };
