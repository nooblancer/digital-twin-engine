'use client';

import { motion } from 'framer-motion';
import { useStore } from '@/store';

interface KalmanGainIndicatorProps {
  sensorId: string;
}

/**
 * KalmanGainIndicator — Dual progress bar showing the EnKF trust ratio
 * between model predictions and sensor observations.
 *
 * K close to 1 = trusting sensor more (violet bar fills)
 * K close to 0 = trusting model more (emerald bar fills)
 *
 * Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5
 */
export function KalmanGainIndicator({ sensorId }: KalmanGainIndicatorProps) {
  const kalmanGain = useStore((state) => state.latestKalmanGain[sensorId] ?? null);

  const sensorTrust = kalmanGain !== null ? kalmanGain * 100 : 0;
  const modelTrust = kalmanGain !== null ? (1 - kalmanGain) * 100 : 0;
  const hasData = kalmanGain !== null;

  return (
    <div className="flex flex-col gap-3 p-4 rounded-lg bg-[#12141a] border border-white/[0.06]">
      <h3 className="text-sm font-medium text-[hsl(210,20%,92%)]">
        Kalman Gain Trust
      </h3>

      {!hasData ? (
        <p className="text-xs text-[hsl(215,12%,58%)]">Waiting for data…</p>
      ) : (
        <>
          {/* Trusting Sensor bar */}
          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between">
              <span className="text-xs text-[hsl(215,12%,58%)]">
                Trusting Sensor
              </span>
              <span className="text-xs font-mono text-violet-400">
                {sensorTrust.toFixed(1)}%
              </span>
            </div>
            <div className="relative h-3 w-full rounded-full bg-white/[0.06] overflow-hidden">
              <motion.div
                className="absolute inset-y-0 left-0 rounded-full"
                style={{ backgroundColor: '#7c3aed' }}
                initial={{ width: '0%' }}
                animate={{ width: `${sensorTrust}%` }}
                transition={{ type: 'spring', stiffness: 120, damping: 20 }}
              />
            </div>
          </div>

          {/* Trusting Model bar */}
          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between">
              <span className="text-xs text-[hsl(215,12%,58%)]">
                Trusting Model
              </span>
              <span className="text-xs font-mono text-emerald-400">
                {modelTrust.toFixed(1)}%
              </span>
            </div>
            <div className="relative h-3 w-full rounded-full bg-white/[0.06] overflow-hidden">
              <motion.div
                className="absolute inset-y-0 left-0 rounded-full"
                style={{ backgroundColor: '#10b981' }}
                initial={{ width: '0%' }}
                animate={{ width: `${modelTrust}%` }}
                transition={{ type: 'spring', stiffness: 120, damping: 20 }}
              />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
