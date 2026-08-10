'use client';

import { useState } from 'react';
import type { SubsystemState } from '@/types/digital-twin';

export interface EngineSchematicProps {
  subsystems: SubsystemState[];
}

const CLASSIFICATION_COLORS: Record<SubsystemState['classification'], string> = {
  nominal: '#22c55e',
  degraded: '#f59e0b',
  critical: '#ef4444',
  unknown: '#9ca3af',
};

const CLASSIFICATION_LABELS: Record<SubsystemState['classification'], string> = {
  nominal: '✓',
  degraded: '⚠',
  critical: '✗',
  unknown: '?',
};

interface SubsystemRegion {
  id: string;
  label: string;
  path: string;
  labelX: number;
  labelY: number;
}

/**
 * SVG regions representing a simplified turbofan engine cross-section.
 * Arranged left-to-right: Fan, LPC, HPC, Combustor, HPT, LPT.
 * Each region uses a path to define its shape within a 800x400 viewBox.
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
    path: 'M 610,100 L 740,60 L 770,80 L 770,320 L 740,340 L 610,300 L 610,100 Z',
    labelX: 690,
    labelY: 200,
  },
];

function getSubsystemState(
  subsystems: SubsystemState[],
  regionId: string
): SubsystemState {
  const found = subsystems.find(
    (s) => s.name.toLowerCase() === regionId.toLowerCase()
  );
  return found ?? { name: regionId, healthScore: 0, classification: 'unknown' };
}

export function EngineSchematic({ subsystems }: EngineSchematicProps) {
  const [tooltip, setTooltip] = useState<{
    visible: boolean;
    x: number;
    y: number;
    content: { name: string; score: string; classification: string };
  }>({ visible: false, x: 0, y: 0, content: { name: '', score: '', classification: '' } });

  function handleMouseEnter(
    event: React.MouseEvent<SVGGElement>,
    state: SubsystemState,
    region: SubsystemRegion
  ) {
    setTooltip({
      visible: true,
      x: region.labelX,
      y: region.labelY - 60,
      content: {
        name: region.label,
        score: state.healthScore.toFixed(2),
        classification: state.classification,
      },
    });
  }

  function handleMouseLeave() {
    setTooltip((prev) => ({ ...prev, visible: false }));
  }

  return (
    <div className="w-full" role="img" aria-label="Turbofan engine schematic showing subsystem health">
      <svg
        viewBox="0 0 800 400"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-auto"
        preserveAspectRatio="xMidYMid meet"
        aria-hidden="true"
      >
        {/* Engine casing outline */}
        <rect
          x="5"
          y="35"
          width="770"
          height="330"
          rx="12"
          ry="12"
          fill="none"
          stroke="#374151"
          strokeWidth="2"
          opacity="0.3"
        />

        {SUBSYSTEM_REGIONS.map((region) => {
          const state = getSubsystemState(subsystems, region.id);
          const fillColor = CLASSIFICATION_COLORS[state.classification];
          const indicator = CLASSIFICATION_LABELS[state.classification];

          return (
            <g
              key={region.id}
              data-testid={`subsystem-${region.id}`}
              role="button"
              aria-label={`${region.label}: ${state.classification}, health score ${state.healthScore.toFixed(2)}`}
              tabIndex={0}
              onMouseEnter={(e) => handleMouseEnter(e, state, region)}
              onMouseLeave={handleMouseLeave}
              onFocus={(e) => handleMouseEnter(e as unknown as React.MouseEvent<SVGGElement>, state, region)}
              onBlur={handleMouseLeave}
              style={{ cursor: 'pointer' }}
            >
              <path
                d={region.path}
                fill={fillColor}
                fillOpacity={0.3}
                stroke={fillColor}
                strokeWidth="2"
              />
              {/* Subsystem name label */}
              <text
                x={region.labelX}
                y={region.labelY - 10}
                textAnchor="middle"
                fontSize="14"
                fontWeight="600"
                fill="#e5e7eb"
                pointerEvents="none"
              >
                {region.label}
              </text>
              {/* Classification indicator (not color-only) */}
              <text
                x={region.labelX}
                y={region.labelY + 16}
                textAnchor="middle"
                fontSize="18"
                fill="#f9fafb"
                pointerEvents="none"
                aria-hidden="true"
              >
                {indicator}
              </text>
            </g>
          );
        })}

        {/* Tooltip */}
        {tooltip.visible && (
          <g data-testid="schematic-tooltip" pointerEvents="none">
            <rect
              x={tooltip.x - 70}
              y={tooltip.y - 20}
              width="140"
              height="56"
              rx="6"
              fill="#1f2937"
              stroke="#4b5563"
              strokeWidth="1"
            />
            <text
              x={tooltip.x}
              y={tooltip.y}
              textAnchor="middle"
              fontSize="12"
              fontWeight="600"
              fill="#f9fafb"
            >
              {tooltip.content.name}
            </text>
            <text
              x={tooltip.x}
              y={tooltip.y + 16}
              textAnchor="middle"
              fontSize="11"
              fill="#d1d5db"
            >
              Score: {tooltip.content.score}
            </text>
            <text
              x={tooltip.x}
              y={tooltip.y + 30}
              textAnchor="middle"
              fontSize="11"
              fill="#d1d5db"
            >
              {tooltip.content.classification}
            </text>
          </g>
        )}
      </svg>

      {/* Screen reader accessible list of subsystem health */}
      <ul className="sr-only">
        {SUBSYSTEM_REGIONS.map((region) => {
          const state = getSubsystemState(subsystems, region.id);
          return (
            <li key={region.id}>
              {region.label}: {state.classification}, health score{' '}
              {state.healthScore.toFixed(2)}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
