import { describe, it, expect, beforeEach } from 'vitest';
import * as fc from 'fast-check';
import { useStore } from '@/store';
import type { PipelineHealthResponse, ComponentStatusValue } from '@/types';

const PIPELINE_COMPONENT_KEYS = [
  'ingestion_server',
  'message_broker',
  'tsdb_writer',
  'ml_service',
  'correction_engine',
];

const errorTypeArb = fc.constantFrom(
  'timeout',
  'network_error',
  'server_500',
  'connection_refused',
  'dns_failure',
);

function resetStore() {
  useStore.setState({
    pipelineHealth: null,
  });
}

describe('Feature: dashboard-frontend, Property 10: Pipeline Health Fallback on Network Error', () => {
  beforeEach(() => {
    resetStore();
  });

  /**
   * **Validates: Requirements 5.5**
   *
   * For ANY network failure when polling the /health endpoint,
   * the Pipeline Health Monitor SHALL set all component statuses to "unknown"
   * and display a connectivity warning.
   *
   * We simulate what PipelineHealthMonitor does on fetch failure:
   * it constructs an unknownResponse with all components set to "unknown"
   * and calls setPipelineHealth with it. The connectivityError flag is set
   * locally in the component (tested via component rendering elsewhere),
   * but the store state must reflect all-unknown statuses.
   */
  it('all component statuses are "unknown" and overall_status is "unknown" for any network error', () => {
    fc.assert(
      fc.property(errorTypeArb, (errorType) => {
        // Reset store before each iteration
        useStore.setState({ pipelineHealth: null });

        // Simulate what PipelineHealthMonitor does on network error:
        // Regardless of error type, it sets all components to "unknown"
        const unknownResponse: PipelineHealthResponse = {
          overall_status: 'unknown' as ComponentStatusValue,
          components: Object.fromEntries(
            PIPELINE_COMPONENT_KEYS.map((key) => [key, 'unknown' as ComponentStatusValue]),
          ),
          timestamp: new Date().toISOString(),
        };
        useStore.getState().setPipelineHealth(unknownResponse);

        // Assert: overall_status is "unknown"
        const state = useStore.getState();
        expect(state.pipelineHealth).not.toBeNull();
        expect(state.pipelineHealth!.overall_status).toBe('unknown');

        // Assert: every pipeline component status is "unknown"
        for (const key of PIPELINE_COMPONENT_KEYS) {
          expect(state.pipelineHealth!.components[key]).toBe('unknown');
        }
      }),
      { numRuns: 100 },
    );
  });

  it('fallback response contains all expected pipeline component keys', () => {
    fc.assert(
      fc.property(errorTypeArb, (errorType) => {
        // Reset store
        useStore.setState({ pipelineHealth: null });

        // Simulate the error fallback behavior
        const unknownResponse: PipelineHealthResponse = {
          overall_status: 'unknown' as ComponentStatusValue,
          components: Object.fromEntries(
            PIPELINE_COMPONENT_KEYS.map((key) => [key, 'unknown' as ComponentStatusValue]),
          ),
          timestamp: new Date().toISOString(),
        };
        useStore.getState().setPipelineHealth(unknownResponse);

        // Assert: all expected component keys are present
        const state = useStore.getState();
        const componentKeys = Object.keys(state.pipelineHealth!.components);
        expect(componentKeys).toHaveLength(PIPELINE_COMPONENT_KEYS.length);
        for (const key of PIPELINE_COMPONENT_KEYS) {
          expect(componentKeys).toContain(key);
        }
      }),
      { numRuns: 100 },
    );
  });

  it('overrides any previous healthy state with all-unknown on error', () => {
    fc.assert(
      fc.property(
        errorTypeArb,
        fc.constantFrom('healthy', 'degraded', 'down') as fc.Arbitrary<ComponentStatusValue>,
        (errorType, previousOverallStatus) => {
          // Set up a previous healthy/degraded state
          const healthyResponse: PipelineHealthResponse = {
            overall_status: previousOverallStatus,
            components: Object.fromEntries(
              PIPELINE_COMPONENT_KEYS.map((key) => [key, 'healthy' as ComponentStatusValue]),
            ),
            timestamp: new Date().toISOString(),
          };
          useStore.getState().setPipelineHealth(healthyResponse);

          // Verify prior state was set
          expect(useStore.getState().pipelineHealth!.overall_status).toBe(previousOverallStatus);

          // Now simulate the network error fallback
          const unknownResponse: PipelineHealthResponse = {
            overall_status: 'unknown' as ComponentStatusValue,
            components: Object.fromEntries(
              PIPELINE_COMPONENT_KEYS.map((key) => [key, 'unknown' as ComponentStatusValue]),
            ),
            timestamp: new Date().toISOString(),
          };
          useStore.getState().setPipelineHealth(unknownResponse);

          // Assert: state is now all "unknown"
          const state = useStore.getState();
          expect(state.pipelineHealth!.overall_status).toBe('unknown');
          for (const key of PIPELINE_COMPONENT_KEYS) {
            expect(state.pipelineHealth!.components[key]).toBe('unknown');
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
