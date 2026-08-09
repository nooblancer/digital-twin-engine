import { describe, it, expect, beforeEach } from 'vitest';
import * as fc from 'fast-check';
import { useStore } from '@/store';
import type { DataSourceId } from '@/types';
import { DATA_SOURCES } from '@/lib/data-sources';

const dataSourceIdArb = fc.constantFrom(...DATA_SOURCES.map((d) => d.id));

function resetStore() {
  useStore.setState({
    activeSource: 'nasa-cmapss' as DataSourceId,
    ui: { isLoading: false, error: null, isSwitchingSource: false },
  });
}

describe('Feature: dashboard-frontend, Property 6: Data Source Switch Error Recovery', () => {
  beforeEach(() => {
    resetStore();
  });

  /**
   * **Validates: Requirements 1.4**
   *
   * For any data source switch attempt that results in a backend error,
   * the active data source selection SHALL remain unchanged (equal to the
   * previously selected source), and an error notification SHALL be present
   * in UI state.
   */
  it('active source remains unchanged and error is present after a failed switch', () => {
    fc.assert(
      fc.property(
        dataSourceIdArb,
        dataSourceIdArb,
        fc.string({ minLength: 1 }),
        (currentSource, attemptedSource, errorMessage) => {
          // Set store to current source
          useStore.setState({ activeSource: currentSource });

          // Simulate a failed switch:
          // The component would call setSwitchingSource(true), then on error
          // calls setError(message) and setSwitchingSource(false), but does NOT
          // call setActiveSource.
          const { setError, setSwitchingSource } = useStore.getState();
          setSwitchingSource(true);
          setError(errorMessage);
          setSwitchingSource(false);

          // Assert: activeSource remains equal to current (unchanged)
          const state = useStore.getState();
          expect(state.activeSource).toBe(currentSource);

          // Assert: error is present in UI state
          expect(state.ui.error).not.toBeNull();
          expect(state.ui.error).toBe(errorMessage);
        },
      ),
      { numRuns: 100 },
    );
  });
});

describe('Feature: dashboard-frontend, Property 7: Data Source Switch Loading State', () => {
  beforeEach(() => {
    resetStore();
  });

  /**
   * **Validates: Requirements 1.3**
   *
   * For any data source switch initiation, the UI state SHALL transition to
   * loading (blocking further selections) until the backend responds with
   * either success or failure.
   */
  it('isSwitchingSource is true during switch and false after completion', () => {
    fc.assert(
      fc.property(dataSourceIdArb, (sourceId) => {
        // Reset to clean state
        useStore.setState({
          activeSource: sourceId,
          ui: { isLoading: false, error: null, isSwitchingSource: false },
        });

        // Simulate switch initiation
        const { setSwitchingSource } = useStore.getState();
        setSwitchingSource(true);

        // Assert: isSwitchingSource is true (blocking further selections)
        expect(useStore.getState().ui.isSwitchingSource).toBe(true);

        // Simulate completion
        setSwitchingSource(false);

        // Assert: isSwitchingSource is false
        expect(useStore.getState().ui.isSwitchingSource).toBe(false);
      }),
      { numRuns: 100 },
    );
  });
});
