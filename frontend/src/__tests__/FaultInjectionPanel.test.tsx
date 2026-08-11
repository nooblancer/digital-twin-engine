/**
 * Unit tests for FaultInjectionPanel component.
 *
 * Tests:
 * - Preset button clicks trigger correct POST fetch calls with expected params
 * - "Clear All" button triggers DELETE request
 * - Error state renders error message without crashing
 * - Active faults list renders fault type badges
 *
 * Requirements: 7.1–7.7
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, act } from '@testing-library/react';

// --- Mock framer-motion ---
vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, className, ...rest }: Record<string, unknown>) => (
      <div className={className as string} {...rest}>
        {children as React.ReactNode}
      </div>
    ),
    li: ({ children, className, ...rest }: Record<string, unknown>) => (
      <li className={className as string} {...rest}>
        {children as React.ReactNode}
      </li>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// --- Mock fetch ---
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// --- Import component AFTER mocks ---
import { FaultInjectionPanel } from '@/components/visualizations/FaultInjectionPanel';

// --- Helpers ---

function mockFetchActiveFaults(faults: unknown[] = []) {
  return {
    ok: true,
    json: async () => faults,
    text: async () => JSON.stringify(faults),
  };
}

function mockFetchError(status: number) {
  return {
    ok: false,
    status,
    text: async () => 'Server error',
  };
}

function mockFetchInjectSuccess() {
  return {
    ok: true,
    json: async () => ({ injection_id: 'test-id-123' }),
    text: async () => '{"injection_id": "test-id-123"}',
  };
}

function mockFetchDeleteSuccess() {
  return {
    ok: true,
    json: async () => ({ message: 'All faults cleared' }),
    text: async () => '{"message": "All faults cleared"}',
  };
}

// --- Tests ---

describe('FaultInjectionPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockFetch.mockReset();
    // Default: active-faults returns empty, other calls succeed
    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      if (url.includes('/sensors/active-faults')) {
        return Promise.resolve(mockFetchActiveFaults([]));
      }
      if (url.includes('/sensors/inject-fault') && options?.method === 'POST') {
        return Promise.resolve(mockFetchInjectSuccess());
      }
      if (url.includes('/sensors/inject-fault') && options?.method === 'DELETE') {
        return Promise.resolve(mockFetchDeleteSuccess());
      }
      return Promise.resolve(mockFetchActiveFaults([]));
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  describe('Preset button clicks trigger correct POST fetch calls', () => {
    it('clicking "Spike HPC Temp +50%" sends POST with spike params', async () => {
      await act(async () => {
        render(<FaultInjectionPanel />);
      });

      const spikeButton = screen.getByText('Spike HPC Temp +50%');
      await act(async () => {
        fireEvent.click(spikeButton);
      });

      const postCalls = mockFetch.mock.calls.filter(
        ([url, opts]: [string, RequestInit?]) =>
          url.includes('/sensors/inject-fault') && opts?.method === 'POST'
      );

      expect(postCalls.length).toBeGreaterThanOrEqual(1);
      const [, options] = postCalls[0];
      const body = JSON.parse(options.body as string);
      expect(body).toEqual({
        sensor_id: 'engine-001-hpc_outlet_temp_total',
        fault_type: 'spike',
        magnitude: 50,
        duration_cycles: 20,
      });
      expect(options.headers).toEqual({ 'Content-Type': 'application/json' });
    });

    it('clicking "Dropout Sensor" sends POST with dropout params', async () => {
      await act(async () => {
        render(<FaultInjectionPanel />);
      });

      const dropoutButton = screen.getByText('Dropout Sensor');
      await act(async () => {
        fireEvent.click(dropoutButton);
      });

      const postCalls = mockFetch.mock.calls.filter(
        ([url, opts]: [string, RequestInit?]) =>
          url.includes('/sensors/inject-fault') && opts?.method === 'POST'
      );

      expect(postCalls.length).toBeGreaterThanOrEqual(1);
      const [, options] = postCalls[0];
      const body = JSON.parse(options.body as string);
      expect(body).toEqual({
        sensor_id: 'engine-001-hpc_outlet_temp_total',
        fault_type: 'dropout',
        magnitude: 1,
        duration_cycles: 15,
      });
    });

    it('clicking "Add Noise" sends POST with noise params', async () => {
      await act(async () => {
        render(<FaultInjectionPanel />);
      });

      const noiseButton = screen.getByText('Add Noise');
      await act(async () => {
        fireEvent.click(noiseButton);
      });

      const postCalls = mockFetch.mock.calls.filter(
        ([url, opts]: [string, RequestInit?]) =>
          url.includes('/sensors/inject-fault') && opts?.method === 'POST'
      );

      expect(postCalls.length).toBeGreaterThanOrEqual(1);
      const [, options] = postCalls[0];
      const body = JSON.parse(options.body as string);
      expect(body).toEqual({
        sensor_id: 'engine-001-hpc_outlet_temp_total',
        fault_type: 'noise',
        magnitude: 5,
        duration_cycles: 30,
      });
    });
  });

  describe('"Clear All" button triggers DELETE request', () => {
    it('clicking "Clear All Faults" sends DELETE to /sensors/inject-fault', async () => {
      // Provide active faults so the button is enabled
      mockFetch.mockImplementation((url: string, options?: RequestInit) => {
        if (url.includes('/sensors/active-faults')) {
          return Promise.resolve(
            mockFetchActiveFaults([
              {
                injection_id: 'fault-1',
                sensor_id: 'engine-001-hpc_outlet_temp_total',
                fault_type: 'spike',
                magnitude: 50,
                remaining_cycles: 10,
                start_cycle: 100,
              },
            ])
          );
        }
        if (url.includes('/sensors/inject-fault') && options?.method === 'DELETE') {
          return Promise.resolve(mockFetchDeleteSuccess());
        }
        return Promise.resolve(mockFetchActiveFaults([]));
      });

      await act(async () => {
        render(<FaultInjectionPanel />);
      });

      // Wait for active faults to load (button becomes enabled)
      await waitFor(() => {
        expect(screen.getByText('Clear All Faults')).not.toBeDisabled();
      });

      await act(async () => {
        fireEvent.click(screen.getByText('Clear All Faults'));
      });

      const deleteCalls = mockFetch.mock.calls.filter(
        ([url, opts]: [string, RequestInit?]) =>
          url.includes('/sensors/inject-fault') && opts?.method === 'DELETE'
      );

      expect(deleteCalls.length).toBeGreaterThanOrEqual(1);
    });

    it('"Clear All Faults" button is disabled when no active faults', async () => {
      await act(async () => {
        render(<FaultInjectionPanel />);
      });

      const clearButton = screen.getByText('Clear All Faults');
      expect(clearButton).toBeDisabled();
    });
  });

  describe('Error state renders error message without crashing', () => {
    it('displays error message when fetch active faults fails', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/sensors/active-faults')) {
          return Promise.resolve(mockFetchError(500));
        }
        return Promise.resolve(mockFetchActiveFaults([]));
      });

      await act(async () => {
        render(<FaultInjectionPanel />);
      });

      await waitFor(() => {
        expect(
          screen.getByText(/Failed to fetch active faults: 500/)
        ).toBeInTheDocument();
      });
    });

    it('displays error message when inject fault fails', async () => {
      mockFetch.mockImplementation((url: string, options?: RequestInit) => {
        if (url.includes('/sensors/active-faults')) {
          return Promise.resolve(mockFetchActiveFaults([]));
        }
        if (url.includes('/sensors/inject-fault') && options?.method === 'POST') {
          return Promise.resolve(mockFetchError(422));
        }
        return Promise.resolve(mockFetchActiveFaults([]));
      });

      await act(async () => {
        render(<FaultInjectionPanel />);
      });

      const spikeButton = screen.getByText('Spike HPC Temp +50%');
      await act(async () => {
        fireEvent.click(spikeButton);
      });

      await waitFor(() => {
        expect(
          screen.getByText(/Inject fault failed \(422\): Server error/)
        ).toBeInTheDocument();
      });
    });

    it('displays error message when network request throws', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/sensors/active-faults')) {
          return Promise.reject(new Error('Network error'));
        }
        return Promise.resolve(mockFetchActiveFaults([]));
      });

      await act(async () => {
        render(<FaultInjectionPanel />);
      });

      await waitFor(() => {
        expect(screen.getByText('Network error')).toBeInTheDocument();
      });
    });

    it('component does not crash when error occurs — still renders buttons', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/sensors/active-faults')) {
          return Promise.resolve(mockFetchError(500));
        }
        return Promise.resolve(mockFetchActiveFaults([]));
      });

      await act(async () => {
        render(<FaultInjectionPanel />);
      });

      await waitFor(() => {
        expect(
          screen.getByText(/Failed to fetch active faults: 500/)
        ).toBeInTheDocument();
      });

      // Buttons are still rendered
      expect(screen.getByText('Spike HPC Temp +50%')).toBeInTheDocument();
      expect(screen.getByText('Dropout Sensor')).toBeInTheDocument();
      expect(screen.getByText('Add Noise')).toBeInTheDocument();
      expect(screen.getByText('Clear All Faults')).toBeInTheDocument();
    });
  });

  describe('Active faults list renders fault type badges', () => {
    it('renders fault type badges for active faults', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/sensors/active-faults')) {
          return Promise.resolve(
            mockFetchActiveFaults([
              {
                injection_id: 'fault-1',
                sensor_id: 'engine-001-hpc_outlet_temp_total',
                fault_type: 'spike',
                magnitude: 50,
                remaining_cycles: 15,
                start_cycle: 100,
              },
              {
                injection_id: 'fault-2',
                sensor_id: 'engine-001-lpc_outlet_temp',
                fault_type: 'dropout',
                magnitude: 1,
                remaining_cycles: 8,
                start_cycle: 102,
              },
            ])
          );
        }
        return Promise.resolve(mockFetchActiveFaults([]));
      });

      await act(async () => {
        render(<FaultInjectionPanel />);
      });

      await waitFor(() => {
        expect(screen.getByText('spike')).toBeInTheDocument();
        expect(screen.getByText('dropout')).toBeInTheDocument();
      });
    });

    it('renders correct sensor IDs alongside badges', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/sensors/active-faults')) {
          return Promise.resolve(
            mockFetchActiveFaults([
              {
                injection_id: 'fault-1',
                sensor_id: 'engine-001-hpc_outlet_temp_total',
                fault_type: 'noise',
                magnitude: 5,
                remaining_cycles: 20,
                start_cycle: 50,
              },
            ])
          );
        }
        return Promise.resolve(mockFetchActiveFaults([]));
      });

      await act(async () => {
        render(<FaultInjectionPanel />);
      });

      await waitFor(() => {
        expect(screen.getByText('noise')).toBeInTheDocument();
        expect(
          screen.getByText('engine-001-hpc_outlet_temp_total')
        ).toBeInTheDocument();
      });
    });

    it('renders remaining cycles for each fault', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/sensors/active-faults')) {
          return Promise.resolve(
            mockFetchActiveFaults([
              {
                injection_id: 'fault-1',
                sensor_id: 'engine-001-hpc_outlet_temp_total',
                fault_type: 'drift',
                magnitude: 3,
                remaining_cycles: 12,
                start_cycle: 80,
              },
            ])
          );
        }
        return Promise.resolve(mockFetchActiveFaults([]));
      });

      await act(async () => {
        render(<FaultInjectionPanel />);
      });

      await waitFor(() => {
        expect(screen.getByText('12 cycles left')).toBeInTheDocument();
      });
    });

    it('shows "No active faults" when list is empty', async () => {
      await act(async () => {
        render(<FaultInjectionPanel />);
      });

      await waitFor(() => {
        expect(screen.getByText('No active faults')).toBeInTheDocument();
      });
    });

    it('shows correct fault count in the heading', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/sensors/active-faults')) {
          return Promise.resolve(
            mockFetchActiveFaults([
              {
                injection_id: 'fault-1',
                sensor_id: 'sensor-a',
                fault_type: 'spike',
                magnitude: 50,
                remaining_cycles: 10,
                start_cycle: 100,
              },
              {
                injection_id: 'fault-2',
                sensor_id: 'sensor-b',
                fault_type: 'noise',
                magnitude: 3,
                remaining_cycles: 5,
                start_cycle: 105,
              },
            ])
          );
        }
        return Promise.resolve(mockFetchActiveFaults([]));
      });

      await act(async () => {
        render(<FaultInjectionPanel />);
      });

      await waitFor(() => {
        expect(screen.getByText('Active Faults (2)')).toBeInTheDocument();
      });
    });
  });
});
