'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import type { SimulationResult } from '@/types/simulation';

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

/** Debounce delay in ms for slider changes before triggering API call. */
const DEBOUNCE_MS = 300;

/** Tick mark positions for the slider. */
const TICK_MARKS = [
  { value: 0.5, label: '0.5x' },
  { value: 1.0, label: '1.0x' },
  { value: 1.5, label: '1.5x' },
  { value: 2.0, label: '2.0x' },
];

interface WhatIfStressSliderProps {
  /** Engine ID to run simulation for. */
  engineId: number;
  /** Callback invoked when simulation data arrives from the API. */
  onSimulationResult: (result: SimulationResult) => void;
  /** Optional horizon_cycles parameter (default: 50). */
  horizonCycles?: number;
}

/**
 * WhatIfStressSlider — Interactive stress factor slider for what-if simulation.
 *
 * Allows users to adjust operational stress from 0.5x to 2.0x. On slider change,
 * calls POST /simulation/what-if with a 300ms debounce and propagates the result
 * to the parent via onSimulationResult callback.
 *
 * Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7
 */
export function WhatIfStressSlider({
  engineId,
  onSimulationResult,
  horizonCycles = 50,
}: WhatIfStressSliderProps) {
  const [stressFactor, setStressFactor] = useState<number>(1.0);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [lastResult, setLastResult] = useState<SimulationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  /** Fetch simulation result from the API for the given stress factor. */
  const fetchSimulation = useCallback(
    async (factor: number) => {
      // Abort any in-flight request
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      const controller = new AbortController();
      abortControllerRef.current = controller;

      setIsLoading(true);
      setError(null);

      try {
        const response = await fetch(`${API_BASE}/simulation/what-if`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            engine_id: engineId,
            stress_factor: factor,
            horizon_cycles: horizonCycles,
          }),
          signal: controller.signal,
        });

        if (!response.ok) {
          const body = await response.text();
          throw new Error(`Simulation failed (${response.status}): ${body}`);
        }

        const data: SimulationResult = await response.json();
        setLastResult(data);
        onSimulationResult(data);
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') {
          // Request was aborted by a newer request — not an error
          return;
        }
        const message =
          err instanceof Error ? err.message : 'Unknown error running simulation';
        setError(message);
      } finally {
        setIsLoading(false);
      }
    },
    [engineId, horizonCycles, onSimulationResult]
  );

  /** Handle slider value change with debounce. */
  const handleSliderChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const value = parseFloat(e.target.value);
      setStressFactor(value);

      // Clear any pending debounced call
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }

      // Schedule API call after debounce period
      debounceRef.current = setTimeout(() => {
        fetchSimulation(value);
      }, DEBOUNCE_MS);
    },
    [fetchSimulation]
  );

  // Load initial projection at stress_factor 1.0 on mount
  useEffect(() => {
    fetchSimulation(1.0);

    return () => {
      // Cleanup pending debounce and abort controller on unmount
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engineId]);

  /** Generate human-readable summary of the simulation result. */
  const getSummaryText = (): string => {
    if (!lastResult) return '';
    if (lastResult.expected_rul === null) {
      return `At ${stressFactor.toFixed(1)}x stress, engine health stays above critical threshold within projection horizon.`;
    }
    return `At ${stressFactor.toFixed(1)}x stress, RUL is estimated at ${lastResult.expected_rul} cycles`;
  };

  return (
    <div className="flex flex-col gap-3 p-4 rounded-lg bg-[#12141a] border border-white/5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-[hsl(210,20%,92%)]">
          What-If Stress Simulation
        </h3>
        {isLoading && (
          <span
            data-testid="loading-indicator"
            className="inline-flex items-center gap-1.5 text-xs text-cyan-400"
          >
            <svg
              className="animate-spin h-3 w-3"
              viewBox="0 0 24 24"
              fill="none"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
            Simulating…
          </span>
        )}
      </div>

      {/* Current value display */}
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-mono font-bold text-cyan-400">
          {stressFactor.toFixed(1)}x
        </span>
        <span className="text-xs text-[hsl(215,12%,58%)]">
          operational stress
        </span>
      </div>

      {/* Range slider */}
      <div className="flex flex-col gap-1">
        <input
          type="range"
          min="0.5"
          max="2.0"
          step="0.1"
          value={stressFactor}
          onChange={handleSliderChange}
          aria-label="Operational stress factor"
          aria-valuemin={0.5}
          aria-valuemax={2.0}
          aria-valuenow={stressFactor}
          className="w-full h-2 rounded-full appearance-none cursor-pointer bg-white/10 accent-cyan-500 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-cyan-400 [&::-webkit-slider-thumb]:shadow-[0_0_8px_rgba(0,212,255,0.5)]"
        />

        {/* Tick marks */}
        <div className="flex justify-between px-0.5">
          {TICK_MARKS.map((tick) => (
            <span
              key={tick.value}
              className={`text-[10px] font-mono ${
                Math.abs(stressFactor - tick.value) < 0.05
                  ? 'text-cyan-400 font-semibold'
                  : 'text-[hsl(215,12%,48%)]'
              }`}
            >
              {tick.label}
            </span>
          ))}
        </div>
      </div>

      {/* Human-readable summary */}
      {lastResult && (
        <p className="text-xs text-[hsl(215,12%,68%)] mt-1">
          {getSummaryText()}
          {lastResult.confidence_interval_90 && (
            <span className="text-[hsl(215,12%,48%)] ml-1">
              (90% CI: {lastResult.confidence_interval_90[0]}–{lastResult.confidence_interval_90[1]} cycles)
            </span>
          )}
        </p>
      )}

      {/* Error message */}
      {error && (
        <p className="text-xs text-red-400 px-2 py-1.5 rounded bg-red-500/10 border border-red-500/20">
          {error}
        </p>
      )}
    </div>
  );
}
