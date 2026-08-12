'use client';

import { useState, useCallback, useRef } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { cn } from '@/lib/utils';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SubsystemHealthData {
  id: string; // e.g. "fan", "lpc", "hpc", "combustor", "hpt", "lpt", "nozzle"
  name: string; // Display name
  healthIndex: number; // 0.0 to 1.0
  sensors: Array<{ name: string; value: number; unit: string }>;
}

export interface TurbofanSchematicProps {
  subsystems: SubsystemHealthData[];
  onSubsystemClick?: (subsystemId: string) => void;
  selectedSubsystem?: string | null;
  showAirflow?: boolean;
  className?: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

interface SubsystemRegion {
  id: string;
  label: string;
  path: string;
  labelX: number;
  labelY: number;
}

/**
 * SVG regions representing a turbofan engine cross-section.
 * Arranged left-to-right: Fan, LPC, HPC, Combustor, HPT, LPT, Nozzle.
 * Each region uses a path within the 800x400 viewBox.
 */
const SUBSYSTEM_REGIONS: SubsystemRegion[] = [
  {
    id: 'fan',
    label: 'Fan',
    path: 'M 30,40 L 130,40 L 150,80 L 150,320 L 130,360 L 30,360 L 10,320 L 10,80 Z',
    labelX: 80,
    labelY: 200,
  },
  {
    id: 'lpc',
    label: 'LPC',
    path: 'M 160,70 L 260,90 L 260,310 L 160,330 L 160,70 Z',
    labelX: 210,
    labelY: 200,
  },
  {
    id: 'hpc',
    label: 'HPC',
    path: 'M 270,90 L 380,110 L 380,290 L 270,310 L 270,90 Z',
    labelX: 325,
    labelY: 200,
  },
  {
    id: 'combustor',
    label: 'Combustor',
    path: 'M 390,110 L 490,120 L 490,280 L 390,290 L 390,110 Z',
    labelX: 440,
    labelY: 200,
  },
  {
    id: 'hpt',
    label: 'HPT',
    path: 'M 500,120 L 600,100 L 600,300 L 500,280 L 500,120 Z',
    labelX: 550,
    labelY: 200,
  },
  {
    id: 'lpt',
    label: 'LPT',
    path: 'M 610,100 L 720,70 L 740,80 L 740,320 L 720,330 L 610,300 L 610,100 Z',
    labelX: 675,
    labelY: 200,
  },
  {
    id: 'nozzle',
    label: 'Nozzle',
    path: 'M 750,80 L 790,120 L 790,280 L 750,320 L 750,80 Z',
    labelX: 770,
    labelY: 200,
  },
];

// ---------------------------------------------------------------------------
// Health → Filter/Color mapping
// ---------------------------------------------------------------------------

function getGlowFilter(healthIndex: number): string {
  if (healthIndex > 0.7) return 'url(#glow-healthy)';
  if (healthIndex > 0.4) return 'url(#glow-warning)';
  return 'url(#glow-critical)';
}

function getStrokeColor(healthIndex: number): string {
  if (healthIndex > 0.7) return '#10b981'; // emerald
  if (healthIndex > 0.4) return '#f59e0b'; // amber
  return '#ef4444'; // crimson
}

function getHealthLabel(healthIndex: number): string {
  if (healthIndex > 0.7) return 'healthy';
  if (healthIndex > 0.4) return 'warning';
  return 'critical';
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TurbofanSchematic({
  subsystems,
  onSubsystemClick,
  selectedSubsystem: controlledSelected,
  showAirflow = true,
  className,
}: TurbofanSchematicProps) {
  const [internalSelected, setInternalSelected] = useState<string | null>(null);
  const selectedId = controlledSelected !== undefined ? controlledSelected : internalSelected;
  const containerRef = useRef<HTMLDivElement>(null);

  const getSubsystemData = useCallback(
    (regionId: string): SubsystemHealthData => {
      const found = subsystems.find(
        (s) => s.id.toLowerCase() === regionId.toLowerCase()
      );
      return found ?? { id: regionId, name: regionId, healthIndex: 1.0, sensors: [] };
    },
    [subsystems]
  );

  const handleSubsystemActivate = useCallback(
    (subsystemId: string) => {
      const newValue = selectedId === subsystemId ? null : subsystemId;
      if (controlledSelected === undefined) {
        setInternalSelected(newValue);
      }
      onSubsystemClick?.(subsystemId);
    },
    [selectedId, controlledSelected, onSubsystemClick]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent, subsystemId: string) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        handleSubsystemActivate(subsystemId);
      }
    },
    [handleSubsystemActivate]
  );

  // Get detail panel data for selected subsystem
  const selectedData = selectedId ? getSubsystemData(selectedId) : null;

  return (
    <div
      ref={containerRef}
      className={cn('relative w-full', className)}
      data-testid="turbofan-schematic"
    >
      {/* SVG Engine Schematic */}
      <svg
        viewBox="0 0 800 400"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-auto"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="Interactive turbofan engine schematic showing subsystem health status"
      >
        <defs>
          {/* Glow filters per health state */}
          <filter id="glow-healthy" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow
              dx="0"
              dy="0"
              stdDeviation="4"
              floodColor="#10b981"
              floodOpacity="0.6"
            />
          </filter>
          <filter id="glow-warning" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow
              dx="0"
              dy="0"
              stdDeviation="4"
              floodColor="#f59e0b"
              floodOpacity="0.6"
            />
          </filter>
          <filter id="glow-critical" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow
              dx="0"
              dy="0"
              stdDeviation="6"
              floodColor="#ef4444"
              floodOpacity="0.8"
            />
          </filter>
        </defs>

        {/* Engine casing outline */}
        <rect
          x="5"
          y="35"
          width="790"
          height="330"
          rx="12"
          ry="12"
          fill="none"
          stroke="#374151"
          strokeWidth="1.5"
          opacity="0.3"
        />

        {/* Subsystem regions */}
        {SUBSYSTEM_REGIONS.map((region) => {
          const data = getSubsystemData(region.id);
          const isSelected = selectedId === region.id;
          const strokeColor = getStrokeColor(data.healthIndex);
          const glowFilter = getGlowFilter(data.healthIndex);
          const healthPct = Math.round(data.healthIndex * 100);

          return (
            <g
              key={region.id}
              data-testid={`subsystem-${region.id}`}
              role="button"
              tabIndex={0}
              aria-label={`${region.label}: ${getHealthLabel(data.healthIndex)}, health ${healthPct}%`}
              aria-expanded={isSelected}
              onClick={() => handleSubsystemActivate(region.id)}
              onKeyDown={(e) => handleKeyDown(e, region.id)}
              style={{
                cursor: 'pointer',
                transition: 'filter 400ms ease',
                filter: isSelected ? undefined : undefined,
              }}
              filter={glowFilter}
            >
              <path
                d={region.path}
                fill="#12141a"
                fillOpacity={0.6}
                stroke={strokeColor}
                strokeWidth={isSelected ? 3 : 2}
                style={{
                  transition: 'stroke 400ms ease, stroke-width 200ms ease',
                }}
              />
              {/* Subsystem name label */}
              <text
                x={region.labelX}
                y={region.labelY - 8}
                textAnchor="middle"
                fontSize="13"
                fontWeight="600"
                fill="#e5e7eb"
                pointerEvents="none"
              >
                {region.label}
              </text>
              {/* Health percentage */}
              <text
                x={region.labelX}
                y={region.labelY + 14}
                textAnchor="middle"
                fontSize="11"
                fill={strokeColor}
                pointerEvents="none"
                style={{ transition: 'fill 400ms ease' }}
              >
                {healthPct}%
              </text>
            </g>
          );
        })}

        {/* Animated airflow paths */}
        {showAirflow && (
          <g aria-hidden="true" pointerEvents="none">
            {/* Primary core airflow path */}
            <path
              d="M 5,200 C 100,200 200,195 400,200 C 600,205 700,200 795,200"
              stroke="#00d4ff"
              strokeWidth="1.5"
              fill="none"
              opacity="0.3"
              strokeDasharray="8 6"
            >
              <animate
                attributeName="stroke-dashoffset"
                from="100"
                to="0"
                dur="3s"
                repeatCount="indefinite"
              />
            </path>

            {/* Upper bypass airflow */}
            <path
              d="M 30,100 C 150,95 300,90 500,95 C 650,100 750,110 795,140"
              stroke="#00d4ff"
              strokeWidth="1"
              fill="none"
              opacity="0.2"
              strokeDasharray="6 8"
            >
              <animate
                attributeName="stroke-dashoffset"
                from="80"
                to="0"
                dur="2.5s"
                repeatCount="indefinite"
              />
            </path>

            {/* Lower bypass airflow */}
            <path
              d="M 30,300 C 150,305 300,310 500,305 C 650,300 750,290 795,260"
              stroke="#00d4ff"
              strokeWidth="1"
              fill="none"
              opacity="0.2"
              strokeDasharray="6 8"
            >
              <animate
                attributeName="stroke-dashoffset"
                from="80"
                to="0"
                dur="2.5s"
                repeatCount="indefinite"
              />
            </path>

            {/* Hot exhaust core flow */}
            <path
              d="M 500,200 C 600,198 700,200 795,200"
              stroke="#ef4444"
              strokeWidth="1"
              fill="none"
              opacity="0.15"
              strokeDasharray="4 6"
            >
              <animate
                attributeName="stroke-dashoffset"
                from="60"
                to="0"
                dur="2s"
                repeatCount="indefinite"
              />
            </path>
          </g>
        )}
      </svg>

      {/* Detail Panel — expanded when a subsystem is selected */}
      <AnimatePresence>
        {selectedData && selectedId && (
          <motion.div
            key={selectedId}
            initial={{ opacity: 0, y: -10, height: 0 }}
            animate={{ opacity: 1, y: 0, height: 'auto' }}
            exit={{ opacity: 0, y: -10, height: 0 }}
            transition={{ duration: 0.3, ease: 'easeInOut' }}
            className="mt-3 overflow-hidden rounded-lg border border-white/[0.06] bg-[#12141a]/90 backdrop-blur-md p-4"
            role="region"
            aria-label={`${selectedData.name} detail panel`}
            data-testid="subsystem-detail-panel"
          >
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-100">
                {selectedData.name}
              </h3>
              <span
                className="text-xs px-2 py-0.5 rounded-full"
                style={{
                  backgroundColor: `${getStrokeColor(selectedData.healthIndex)}20`,
                  color: getStrokeColor(selectedData.healthIndex),
                }}
              >
                {getHealthLabel(selectedData.healthIndex)} — {Math.round(selectedData.healthIndex * 100)}%
              </span>
            </div>

            {selectedData.sensors.length > 0 ? (
              <div className="space-y-2">
                <p className="text-xs text-gray-400 font-medium uppercase tracking-wide">
                  Sensors
                </p>
                <ul className="divide-y divide-white/[0.04]">
                  {selectedData.sensors.map((sensor) => (
                    <li
                      key={sensor.name}
                      className="flex items-center justify-between py-1.5 text-xs"
                    >
                      <span className="text-gray-300 truncate max-w-[60%]">
                        {sensor.name}
                      </span>
                      <span className="text-gray-100 font-mono">
                        {sensor.value.toFixed(2)}{' '}
                        <span className="text-gray-500">{sensor.unit}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="text-xs text-gray-500">No sensor data available.</p>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Screen reader accessible list of subsystem health */}
      <ul className="sr-only">
        {SUBSYSTEM_REGIONS.map((region) => {
          const data = getSubsystemData(region.id);
          return (
            <li key={region.id}>
              {region.label}: {getHealthLabel(data.healthIndex)}, health{' '}
              {Math.round(data.healthIndex * 100)}%
            </li>
          );
        })}
      </ul>
    </div>
  );
}
