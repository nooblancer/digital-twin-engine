import type { StateCreator } from 'zustand';
import type {
  FleetPatternResponse,
  FleetStatsResponse,
  FleetSliceState,
} from '@/types/fleet';

export type FleetSlice = FleetSliceState;

export const createFleetSlice: StateCreator<FleetSlice> = (set) => ({
  // Initial state
  patterns: null,
  stats: null,
  patternsLoading: false,
  statsLoading: false,
  patternsError: null,
  statsError: null,

  // Actions
  setFleetPatterns: (patterns: FleetPatternResponse) =>
    set(() => ({
      patterns,
      patternsError: null,
    })),

  setFleetStats: (stats: FleetStatsResponse) =>
    set(() => ({
      stats,
      statsError: null,
    })),

  setPatternsLoading: (loading: boolean) =>
    set(() => ({
      patternsLoading: loading,
    })),

  setStatsLoading: (loading: boolean) =>
    set(() => ({
      statsLoading: loading,
    })),

  setPatternsError: (error: string | null) =>
    set(() => ({
      patternsError: error,
    })),

  setStatsError: (error: string | null) =>
    set(() => ({
      statsError: error,
    })),

  clearFleetData: () =>
    set(() => ({
      patterns: null,
      stats: null,
      patternsLoading: false,
      statsLoading: false,
      patternsError: null,
      statsError: null,
    })),
});
