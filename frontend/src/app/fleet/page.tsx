'use client';

import { useState, useMemo, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useStore } from '@/store';
import { FleetStatsBar } from '@/components/fleet/FleetStatsBar';
import { FleetNodeGrid } from '@/components/fleet/FleetNodeGrid';
import { FleetPatternConnections } from '@/components/fleet/FleetPatternConnections';

// --- Mock data for when backend isn't running ---

const MOCK_ENGINES: Array<{ id: number; healthIndex: number; rul: number }> = [
  { id: 1, healthIndex: 0.92, rul: 112 },
  { id: 2, healthIndex: 0.78, rul: 85 },
  { id: 3, healthIndex: 0.55, rul: 42 },
  { id: 4, healthIndex: 0.33, rul: 18 },
  { id: 5, healthIndex: 0.88, rul: 97 },
  { id: 6, healthIndex: 0.65, rul: 58 },
];

// --- Page ---

export default function FleetOverviewPage() {
  const router = useRouter();

  // Subscribe to real-time WebSocket updates
  useWebSocket();

  const engines = useStore((state) => state.engines);

  // Node positions state — passed from FleetNodeGrid to FleetPatternConnections
  const [nodePositions, setNodePositions] = useState<Map<number, { x: number; y: number }>>(
    () => new Map()
  );

  // Derive engine list for the grid from store, with mock fallback
  const engineNodes = useMemo(() => {
    const storeEngines = Object.values(engines);
    if (storeEngines.length > 0) {
      return storeEngines.map((e) => ({
        id: e.engineId,
        healthIndex: e.healthIndex,
        rul: e.rul,
      }));
    }
    // Fallback to mock data so the page works without backend
    return MOCK_ENGINES;
  }, [engines]);

  // Navigate to engine detail page on selection
  const handleEngineSelect = useCallback(
    (engineId: number) => {
      router.push(`/engine/${engineId}`);
    },
    [router]
  );

  // Handle node positions reported by FleetNodeGrid
  const handleNodePositionsChange = useCallback(
    (positions: Map<number, { x: number; y: number }>) => {
      setNodePositions(positions);
    },
    []
  );

  return (
    <div className="flex flex-col h-full min-h-screen bg-background">
      {/* Sticky stats bar at top */}
      <div className="sticky top-0 z-10 px-4 sm:px-6 pt-4 pb-2 bg-background/80 backdrop-blur-sm border-b border-white/5">
        <FleetStatsBar />
      </div>

      {/* Page header */}
      <header className="px-4 sm:px-6 pt-4 pb-2">
        <h1 className="text-2xl font-semibold text-foreground">Fleet Overview</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {engineNodes.length > 0
            ? `Monitoring ${engineNodes.length} engine${engineNodes.length !== 1 ? 's' : ''} — click a node to inspect`
            : 'Real-time fleet health monitoring'}
        </p>
      </header>

      {/* Main visualization: FleetNodeGrid with FleetPatternConnections SVG overlay */}
      <main aria-label="Fleet engine visualization" className="relative flex-1 mx-4 sm:mx-6 mb-6">
        <FleetNodeGrid
          engines={engineNodes}
          onEngineSelect={handleEngineSelect}
          onNodePositionsChange={handleNodePositionsChange}
        />
        <FleetPatternConnections nodePositions={nodePositions} />
      </main>
    </div>
  );
}
