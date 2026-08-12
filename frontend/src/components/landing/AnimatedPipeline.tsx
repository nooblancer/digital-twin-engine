'use client';

import { useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { usePrefersReducedMotion } from '@/lib/animations';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PipelineStage {
  id: string;
  label: string;
  description: string;
  cx: number;
  cy: number;
  color: string;
  glowColor: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STAGES: PipelineStage[] = [
  {
    id: 'sensors',
    label: 'Sensors',
    description:
      'Raw telemetry from 21 engine sensors: temperature, pressure, speed, and vibration channels streaming at high frequency.',
    cx: 100,
    cy: 150,
    color: '#00d4ff',
    glowColor: 'rgba(0, 212, 255, 0.4)',
  },
  {
    id: 'ml-prediction',
    label: 'ML Prediction',
    description:
      'Machine learning model processes sensor data to predict engine degradation and remaining useful life (RUL).',
    cx: 300,
    cy: 150,
    color: '#7c3aed',
    glowColor: 'rgba(124, 58, 237, 0.4)',
  },
  {
    id: 'enkf-correction',
    label: 'EnKF Correction',
    description:
      'Ensemble Kalman Filter fuses ML predictions with real sensor observations, reducing noise and correcting drift in real-time.',
    cx: 500,
    cy: 150,
    color: '#10b981',
    glowColor: 'rgba(16, 185, 129, 0.4)',
  },
  {
    id: 'output',
    label: 'Output',
    description:
      'Corrected state estimates, confidence intervals, and health indices delivered to the dashboard with < 85ms latency.',
    cx: 700,
    cy: 150,
    color: '#f59e0b',
    glowColor: 'rgba(245, 158, 11, 0.4)',
  },
];

/** SVG connector paths between adjacent stages */
const CONNECTORS = [
  { from: 'sensors', to: 'ml-prediction', path: 'M 145,150 C 190,150 210,150 255,150' },
  { from: 'ml-prediction', to: 'enkf-correction', path: 'M 345,150 C 390,150 410,150 455,150' },
  { from: 'enkf-correction', to: 'output', path: 'M 545,150 C 590,150 610,150 655,150' },
];

const NODE_RX = 45;
const NODE_RY = 30;

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StageNode({
  stage,
  isActive,
  isHovered,
  reducedMotion,
  onHoverStart,
  onHoverEnd,
}: {
  stage: PipelineStage;
  isActive: boolean;
  isHovered: boolean;
  reducedMotion: boolean;
  onHoverStart: () => void;
  onHoverEnd: () => void;
}) {
  const baseOpacity = reducedMotion || isActive ? 1 : 0.5;

  return (
    <g
      role="img"
      aria-label={`Pipeline stage: ${stage.label} — ${stage.description}`}
      onMouseEnter={onHoverStart}
      onMouseLeave={onHoverEnd}
      onFocus={onHoverStart}
      onBlur={onHoverEnd}
      tabIndex={0}
      className="focus-visible:outline-none"
      style={{ cursor: 'pointer' }}
    >
      {/* Focus indicator ring (visible on keyboard focus) */}
      <ellipse
        cx={stage.cx}
        cy={stage.cy}
        rx={NODE_RX + 10}
        ry={NODE_RY + 10}
        fill="none"
        stroke="hsl(192, 45%, 55%)"
        strokeWidth={2}
        opacity={0}
        className="focus-ring"
      />

      {/* Glow background (always visible when active or reduced-motion) */}
      <ellipse
        cx={stage.cx}
        cy={stage.cy}
        rx={NODE_RX + 6}
        ry={NODE_RY + 6}
        fill={stage.glowColor}
        opacity={isActive || reducedMotion ? 0.5 : 0}
        style={{ transition: 'opacity 300ms ease' }}
      />

      {/* Main node shape */}
      <motion.ellipse
        cx={stage.cx}
        cy={stage.cy}
        rx={NODE_RX}
        ry={NODE_RY}
        fill="#12141a"
        stroke={stage.color}
        strokeWidth={isHovered ? 3 : 2}
        animate={{
          opacity: baseOpacity,
          filter: isActive || reducedMotion
            ? `drop-shadow(0 0 8px ${stage.glowColor})`
            : 'drop-shadow(0 0 0px transparent)',
        }}
        transition={{ duration: 0.3 }}
      />

      {/* Label */}
      <text
        x={stage.cx}
        y={stage.cy + 1}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize="11"
        fontWeight="600"
        fill="#e5e7eb"
        pointerEvents="none"
      >
        {stage.label}
      </text>
    </g>
  );
}

function ConnectorLine({
  pathD,
  fromColor,
  toColor,
  gradientId,
  isActive,
  reducedMotion,
}: {
  pathD: string;
  fromColor: string;
  toColor: string;
  gradientId: string;
  isActive: boolean;
  reducedMotion: boolean;
}) {
  return (
    <>
      {/* Static gradient underline */}
      <path
        d={pathD}
        stroke={`url(#${gradientId})`}
        strokeWidth="2"
        fill="none"
        opacity={0.2}
      />
      {/* Animated dashed overlay */}
      <path
        d={pathD}
        stroke={`url(#${gradientId})`}
        strokeWidth="2"
        fill="none"
        opacity={isActive || reducedMotion ? 0.8 : 0.4}
        strokeDasharray="8 6"
        style={{ transition: 'opacity 300ms ease' }}
      >
        {!reducedMotion && (
          <animate
            attributeName="stroke-dashoffset"
            from="100"
            to="0"
            dur="2s"
            repeatCount="indefinite"
          />
        )}
      </path>
    </>
  );
}

function Particle({
  pathD,
  color,
  delay,
  reducedMotion,
}: {
  pathD: string;
  color: string;
  delay: number;
  reducedMotion: boolean;
}) {
  if (reducedMotion) return null;

  return (
    <circle r="3" fill={color} opacity="0.9">
      <animateMotion
        dur="2.5s"
        repeatCount="indefinite"
        begin={`${delay}s`}
        path={pathD}
      />
      <animate
        attributeName="opacity"
        values="0;0.9;0.9;0"
        keyTimes="0;0.1;0.9;1"
        dur="2.5s"
        repeatCount="indefinite"
        begin={`${delay}s`}
      />
    </circle>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function AnimatedPipeline() {
  const reducedMotion = usePrefersReducedMotion();
  const [hoveredStage, setHoveredStage] = useState<string | null>(null);
  const [activeStageIndex, setActiveStageIndex] = useState<number>(0);

  // Cycle through stages to create "lighting up" effect
  // We track which stage is currently "active" via a cycling animation
  // When reduced motion is on, all stages are active
  const handleHoverStart = useCallback((stageId: string) => {
    setHoveredStage(stageId);
  }, []);

  const handleHoverEnd = useCallback(() => {
    setHoveredStage(null);
  }, []);

  // Determine which stage is "active" (lit up)
  // In reduced motion: all stages are always active
  // On hover: the hovered stage is active
  // Otherwise: cycle via CSS animation timing (we use a simple approach: all active during particle flow)
  const isStageActive = useCallback(
    (stageId: string, _index: number): boolean => {
      if (reducedMotion) return true;
      if (hoveredStage === stageId) return true;
      // When not hovered, all stages glow subtly (the particles provide the "lit up" progression)
      return !hoveredStage;
    },
    [reducedMotion, hoveredStage]
  );

  return (
    <div className="w-full max-w-4xl mx-auto" data-testid="animated-pipeline">
      <svg
        viewBox="0 0 800 300"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-auto"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="Animated data pipeline showing four stages: Sensors, ML Prediction, EnKF Correction, and Output, connected by flowing data particles"
      >
        <defs>
          {/* Gradient definitions for connector lines */}
          {CONNECTORS.map((conn, i) => {
            const fromStage = STAGES.find((s) => s.id === conn.from)!;
            const toStage = STAGES.find((s) => s.id === conn.to)!;
            return (
              <linearGradient
                key={`grad-${i}`}
                id={`pipeline-grad-${i}`}
                x1="0%"
                y1="0%"
                x2="100%"
                y2="0%"
              >
                <stop offset="0%" stopColor={fromStage.color} />
                <stop offset="100%" stopColor={toStage.color} />
              </linearGradient>
            );
          })}

          {/* Glow filter for particles */}
          <filter id="particle-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Connector lines between stages */}
        {CONNECTORS.map((conn, i) => (
          <ConnectorLine
            key={`conn-${i}`}
            pathD={conn.path}
            fromColor={STAGES.find((s) => s.id === conn.from)!.color}
            toColor={STAGES.find((s) => s.id === conn.to)!.color}
            gradientId={`pipeline-grad-${i}`}
            isActive={!hoveredStage}
            reducedMotion={reducedMotion}
          />
        ))}

        {/* Particles flowing along connectors */}
        <g filter="url(#particle-glow)" aria-hidden="true">
          {CONNECTORS.map((conn, i) => {
            const fromStage = STAGES.find((s) => s.id === conn.from)!;
            // Pause particles on the connector leading TO the hovered stage
            const toStage = STAGES.find((s) => s.id === conn.to)!;
            if (hoveredStage === toStage.id || hoveredStage === fromStage.id) {
              return null;
            }
            return (
              <g key={`particles-${i}`}>
                <Particle
                  pathD={conn.path}
                  color={fromStage.color}
                  delay={0}
                  reducedMotion={reducedMotion}
                />
                <Particle
                  pathD={conn.path}
                  color={fromStage.color}
                  delay={0.8}
                  reducedMotion={reducedMotion}
                />
                <Particle
                  pathD={conn.path}
                  color={toStage.color}
                  delay={1.6}
                  reducedMotion={reducedMotion}
                />
              </g>
            );
          })}
        </g>

        {/* Stage nodes */}
        {STAGES.map((stage, index) => (
          <StageNode
            key={stage.id}
            stage={stage}
            isActive={isStageActive(stage.id, index)}
            isHovered={hoveredStage === stage.id}
            reducedMotion={reducedMotion}
            onHoverStart={() => handleHoverStart(stage.id)}
            onHoverEnd={handleHoverEnd}
          />
        ))}
      </svg>

      {/* Tooltip on hover */}
      <AnimatePresence>
        {hoveredStage && !reducedMotion && (
          <motion.div
            key={hoveredStage}
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
            className="mt-3 mx-auto max-w-md rounded-lg border border-white/[0.06] bg-[#12141a]/90 backdrop-blur-md p-3 text-center"
            role="tooltip"
            aria-live="polite"
          >
            <p className="text-sm font-semibold text-gray-100 mb-1">
              {STAGES.find((s) => s.id === hoveredStage)?.label}
            </p>
            <p className="text-xs text-gray-400">
              {STAGES.find((s) => s.id === hoveredStage)?.description}
            </p>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Reduced motion: always show all descriptions */}
      {reducedMotion && (
        <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3">
          {STAGES.map((stage) => (
            <div
              key={stage.id}
              className="rounded-lg border border-white/[0.06] bg-[#12141a]/90 p-3"
            >
              <p
                className="text-xs font-semibold mb-1"
                style={{ color: stage.color }}
              >
                {stage.label}
              </p>
              <p className="text-xs text-gray-400">{stage.description}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
