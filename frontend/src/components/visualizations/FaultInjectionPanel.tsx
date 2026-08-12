'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { GlowCard } from '@/components/ui/GlowCard';
import type { ActiveFault, InjectFaultParams } from '@/types/simulation';

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

/** Preset fault injection configurations for quick demo use. */
const FAULT_PRESETS: { label: string; params: InjectFaultParams }[] = [
  {
    label: 'Spike HPC Temp +50%',
    params: {
      sensor_id: 'engine-001-hpc_outlet_temp_total',
      fault_type: 'spike',
      magnitude: 50,
      duration_cycles: 20,
    },
  },
  {
    label: 'Dropout Sensor',
    params: {
      sensor_id: 'engine-001-hpc_outlet_temp_total',
      fault_type: 'dropout',
      magnitude: 1,
      duration_cycles: 15,
    },
  },
  {
    label: 'Add Noise',
    params: {
      sensor_id: 'engine-001-hpc_outlet_temp_total',
      fault_type: 'noise',
      magnitude: 5,
      duration_cycles: 30,
    },
  },
];

/** Color mapping for fault type badges. */
const FAULT_TYPE_COLORS: Record<ActiveFault['fault_type'], string> = {
  spike: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  drift: 'bg-violet-500/20 text-violet-400 border-violet-500/30',
  dropout: 'bg-red-500/20 text-red-400 border-red-500/30',
  noise: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
};

/**
 * FaultInjectionPanel — Control panel for injecting artificial sensor faults.
 *
 * Provides preset buttons for common fault scenarios, a "Clear All" button,
 * and a live list of active faults polled every 2 seconds.
 *
 * Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7
 */
export function FaultInjectionPanel() {
  const [activeFaults, setActiveFaults] = useState<ActiveFault[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isInjecting, setIsInjecting] = useState(false);
  const [justInjected, setJustInjected] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /** Fetch the current list of active faults from the backend. */
  const fetchActiveFaults = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/sensors/active-faults`);
      if (!response.ok) {
        throw new Error(`Failed to fetch active faults: ${response.status}`);
      }
      const data: ActiveFault[] = await response.json();
      setActiveFaults(data);
      setError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error fetching faults';
      setError(message);
    }
  }, []);

  /** Inject a fault using the given preset parameters. */
  const injectFault = useCallback(
    async (params: InjectFaultParams) => {
      setIsInjecting(true);
      setError(null);
      try {
        const response = await fetch(`${API_BASE}/sensors/inject-fault`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(params),
        });
        if (!response.ok) {
          const body = await response.text();
          throw new Error(`Inject fault failed (${response.status}): ${body}`);
        }
        // Refresh active faults after successful injection
        await fetchActiveFaults();
        // Trigger glow animation
        setJustInjected(true);
        setTimeout(() => setJustInjected(false), 500);
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Unknown error injecting fault';
        setError(message);
      } finally {
        setIsInjecting(false);
      }
    },
    [fetchActiveFaults]
  );

  /** Clear all active faults. */
  const clearAllFaults = useCallback(async () => {
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/sensors/inject-fault`, {
        method: 'DELETE',
      });
      if (!response.ok) {
        throw new Error(`Clear faults failed: ${response.status}`);
      }
      // Refresh active faults after clearing
      await fetchActiveFaults();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error clearing faults';
      setError(message);
    }
  }, [fetchActiveFaults]);

  // Poll active faults every 2 seconds
  useEffect(() => {
    fetchActiveFaults();
    pollRef.current = setInterval(fetchActiveFaults, 2000);

    return () => {
      if (pollRef.current !== null) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [fetchActiveFaults]);

  return (
    <GlowCard glowColor="cyan" isActive={justInjected} className="hover-depth">
      <div className="flex flex-col gap-4 p-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-[hsl(210,20%,92%)]">
            Fault Injection
          </h3>
          <button
            onClick={clearAllFaults}
            disabled={activeFaults.length === 0}
            className="px-3 py-1 text-xs font-medium rounded border border-mission-crimson/30 text-red-400 hover:bg-red-500/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Clear All Faults
          </button>
        </div>

        {/* Preset buttons */}
        <div className="flex flex-wrap gap-2">
          {FAULT_PRESETS.map((preset) => (
            <button
              key={preset.label}
              onClick={() => injectFault(preset.params)}
              disabled={isInjecting}
              className="px-3 py-1.5 text-xs font-medium rounded border border-mission-cyan/30 text-cyan-400 bg-mission-cyan/10 hover:bg-mission-cyan/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {preset.label}
            </button>
          ))}
        </div>

        {/* Error message */}
        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="px-3 py-2 text-xs text-red-400 rounded bg-red-500/10 border border-mission-crimson/20"
            >
              {error}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Active faults list */}
        <div className="flex flex-col gap-2">
          <span className="text-xs text-[hsl(215,12%,58%)]">
            Active Faults ({activeFaults.length})
          </span>

          {activeFaults.length === 0 ? (
            <p className="text-xs text-[hsl(215,12%,42%)] italic">
              No active faults
            </p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              <AnimatePresence>
                {activeFaults.map((fault) => (
                  <motion.li
                    key={fault.injection_id}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: 8 }}
                    transition={{ duration: 0.2 }}
                    className="flex items-center justify-between px-3 py-1.5 rounded bg-white/[0.03] border border-white/[0.06]"
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-flex items-center px-1.5 py-0.5 text-[10px] font-semibold uppercase rounded border ${FAULT_TYPE_COLORS[fault.fault_type]}`}
                      >
                        {fault.fault_type}
                      </span>
                      <span className="text-xs text-[hsl(210,20%,78%)] truncate max-w-[160px]">
                        {fault.sensor_id}
                      </span>
                    </div>
                    <span className="text-[10px] font-mono text-[hsl(215,12%,58%)]">
                      {fault.remaining_cycles} cycles left
                    </span>
                  </motion.li>
                ))}
              </AnimatePresence>
            </ul>
          )}
        </div>
      </div>
    </GlowCard>
  );
}
