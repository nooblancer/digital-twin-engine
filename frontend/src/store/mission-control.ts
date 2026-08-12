import type { StateCreator } from 'zustand';
import type {
  MissionControlState,
  PredictiveAlert,
  AnomalyAnalysisResponse,
  PerformanceMetrics,
  BenchmarkMetrics,
} from '@/types/mission-control';

export type MissionControlSlice = MissionControlState;

export const createMissionControlSlice: StateCreator<MissionControlSlice> = (set) => ({
  // Initial state
  predictiveAlerts: [],
  anomalyAnalysis: {},
  performanceMetrics: null,
  benchmarkMetrics: null,
  totalEventCount: 0,

  // Actions
  addPredictiveAlert: (alert: PredictiveAlert) =>
    set((state) => ({
      predictiveAlerts: [alert, ...state.predictiveAlerts],
    })),

  dismissAlert: (alertId: string) =>
    set((state) => ({
      predictiveAlerts: state.predictiveAlerts.filter((a) => a.id !== alertId),
    })),

  setAnomalyAnalysis: (engineId: number, analysis: AnomalyAnalysisResponse) =>
    set((state) => ({
      anomalyAnalysis: {
        ...state.anomalyAnalysis,
        [engineId]: analysis,
      },
    })),

  setPerformanceMetrics: (metrics: PerformanceMetrics) =>
    set(() => ({
      performanceMetrics: metrics,
    })),

  setBenchmarkMetrics: (metrics: BenchmarkMetrics) =>
    set(() => ({
      benchmarkMetrics: metrics,
    })),

  incrementEventCount: () =>
    set((state) => ({
      totalEventCount: state.totalEventCount + 1,
    })),
});
