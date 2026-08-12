/**
 * Unit tests for TelemetryWaterfall component.
 *
 * Tests:
 * - Canvas renders with correct dimensions
 * - Buffer is bounded at VISIBLE_STEPS + 10
 * - Handles empty data gracefully
 * - Fallback behavior when Canvas is unavailable
 *
 * Requirements: 11.1, 11.3, 11.6
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import React from 'react';

// --- Mock Zustand store ---
const mockStoreState = {
  sensorData: {} as Record<string, Array<{ corrected?: number; predicted?: number; raw?: number }>>,
  connection: { status: 'connected' as const },
};

vi.mock('@/store', () => ({
  useStore: (selector: (state: typeof mockStoreState) => unknown) => selector(mockStoreState),
}));

// --- Import after mocks ---
import {
  TelemetryWaterfall,
  WaterfallRingBuffer,
  CELL_WIDTH,
  CELL_HEIGHT,
  VISIBLE_STEPS,
  BUFFER_SIZE,
  DEFAULT_CHANNELS,
  getCellColor,
} from '@/components/visualizations/TelemetryWaterfall';

// --- Helpers ---

function setSensorData(data: Record<string, Array<{ corrected?: number; predicted?: number; raw?: number }>>) {
  mockStoreState.sensorData = data;
}

/**
 * Create a minimal mock CanvasRenderingContext2D for jsdom which doesn't support Canvas natively.
 */
function createMockContext2D(): Partial<CanvasRenderingContext2D> {
  return {
    clearRect: vi.fn(),
    fillRect: vi.fn(),
    fillStyle: '',
    beginPath: vi.fn(),
    stroke: vi.fn(),
    fill: vi.fn(),
  };
}

// --- Tests ---

describe('TelemetryWaterfall', () => {
  let mockGetContext: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    // Reset store state
    mockStoreState.sensorData = {};

    // Mock requestAnimationFrame to call once (not recursively) to avoid stack overflow
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((_cb) => {
      // Don't call callback to avoid infinite loop; just return an id
      return 1;
    });
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});

    // Mock Canvas getContext for jsdom which doesn't support it
    mockGetContext = vi.fn().mockReturnValue(createMockContext2D());
    HTMLCanvasElement.prototype.getContext = mockGetContext as unknown as HTMLCanvasElement['getContext'];
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  describe('Canvas rendering (Requirement 11.1)', () => {
    it('renders a canvas element with correct dimensions for 21 channels × 50 steps', () => {
      const { container } = render(<TelemetryWaterfall />);

      const canvas = container.querySelector('canvas[data-testid="waterfall-canvas"]');
      expect(canvas).not.toBeNull();
      expect(canvas!.getAttribute('width')).toBe(String(VISIBLE_STEPS * CELL_WIDTH));
      expect(canvas!.getAttribute('height')).toBe(String(DEFAULT_CHANNELS.length * CELL_HEIGHT));
    });

    it('renders all 21 sensor channel labels', () => {
      const { container } = render(<TelemetryWaterfall />);

      // Each channel should have a label element
      for (const channel of DEFAULT_CHANNELS) {
        const label = container.querySelector(`[title="${channel}"]`);
        expect(label).not.toBeNull();
      }
    });

    it('renders a color legend below the canvas', () => {
      const { container } = render(<TelemetryWaterfall />);

      // Legend contains "Low" and "High" text
      const allText = container.textContent ?? '';
      expect(allText).toContain('Low');
      expect(allText).toContain('High');
      expect(allText).toContain('Deviation');
    });

    it('renders with custom visibleSteps prop', () => {
      const customSteps = 30;
      const { container } = render(<TelemetryWaterfall visibleSteps={customSteps} />);

      const canvas = container.querySelector('canvas[data-testid="waterfall-canvas"]');
      expect(canvas).not.toBeNull();
      expect(canvas!.getAttribute('width')).toBe(String(customSteps * CELL_WIDTH));
    });

    it('has correct ARIA label for accessibility', () => {
      const { container } = render(<TelemetryWaterfall />);

      const ariaElement = container.querySelector('[role="img"]');
      expect(ariaElement).not.toBeNull();
      expect(ariaElement!.getAttribute('aria-label')).toContain('Telemetry waterfall heatmap');
    });
  });

  describe('Buffer bounded (Requirement 11.3, 11.6)', () => {
    it('BUFFER_SIZE equals VISIBLE_STEPS + 10', () => {
      expect(BUFFER_SIZE).toBe(VISIBLE_STEPS + 10);
    });

    it('WaterfallRingBuffer never exceeds capacity after many pushes', () => {
      const buffer = new WaterfallRingBuffer(BUFFER_SIZE);

      // Push more data than capacity
      for (let i = 0; i < 200; i++) {
        buffer.push(new Array(21).fill(Math.random()));
      }

      expect(buffer.length).toBeLessThanOrEqual(BUFFER_SIZE);
      expect(buffer.length).toBe(BUFFER_SIZE);
    });

    it('WaterfallRingBuffer evicts oldest entries when at capacity', () => {
      const buffer = new WaterfallRingBuffer(BUFFER_SIZE);

      // Push BUFFER_SIZE + 5 entries
      for (let i = 0; i < BUFFER_SIZE + 5; i++) {
        buffer.push(new Array(21).fill(i));
      }

      // Buffer should be exactly at capacity
      expect(buffer.length).toBe(BUFFER_SIZE);

      // The oldest item should be index 5 (first 5 were evicted)
      const oldest = buffer.get(0);
      expect(oldest).not.toBeNull();
      expect(oldest![0]).toBe(5);
    });

    it('WaterfallRingBuffer getRecent returns correct number of items', () => {
      const buffer = new WaterfallRingBuffer(BUFFER_SIZE);

      for (let i = 0; i < 30; i++) {
        buffer.push(new Array(21).fill(i));
      }

      const recent = buffer.getRecent(10);
      expect(recent.length).toBe(10);

      // Most recent should be the last pushed value
      const lastItem = recent[recent.length - 1];
      expect(lastItem).not.toBeNull();
      expect(lastItem![0]).toBe(29);
    });
  });

  describe('Handles empty data (Requirement 11.1)', () => {
    it('renders without crashing when sensorData is empty', () => {
      setSensorData({});
      const { container } = render(<TelemetryWaterfall />);

      const canvas = container.querySelector('canvas[data-testid="waterfall-canvas"]');
      expect(canvas).not.toBeNull();
    });

    it('renders without crashing with no channels specified', () => {
      const { container } = render(<TelemetryWaterfall channels={[]} />);

      // Should render the container but with 0 height canvas
      const canvas = container.querySelector('canvas[data-testid="waterfall-canvas"]');
      expect(canvas).not.toBeNull();
      expect(canvas!.getAttribute('height')).toBe('0');
    });
  });

  describe('Fallback behavior when Canvas unavailable (Requirement 11.6)', () => {
    it('renders an HTML table when Canvas getContext returns null', () => {
      // Override the mock to return null (simulating no canvas support)
      mockGetContext.mockReturnValue(null);

      const { container } = render(<TelemetryWaterfall />);

      // Should render a table-based fallback with role="grid"
      const fallbackGrid = container.querySelector('[role="grid"]');
      expect(fallbackGrid).not.toBeNull();

      // Should have the table with sensor names
      const table = container.querySelector('table');
      expect(table).not.toBeNull();
    });

    it('fallback table shows sensor channel names', () => {
      mockGetContext.mockReturnValue(null);

      const { container } = render(<TelemetryWaterfall />);

      // Verify at least some sensor names are present
      const tableText = container.textContent ?? '';
      expect(tableText).toContain('Fan inlet temp (T2)');
      expect(tableText).toContain('LPT coolant bleed (W32)');
    });
  });

  describe('getCellColor utility', () => {
    it('returns dim cyan for low deviation (0.0)', () => {
      const color = getCellColor(0, 'cyan');
      expect(color).toBe('rgba(0, 212, 255, 0.1)');
    });

    it('returns bright cyan for high deviation (1.0)', () => {
      const color = getCellColor(1, 'cyan');
      expect(color).toBe('rgba(0, 212, 255, 1)');
    });

    it('clamps values above 1.0 to max intensity', () => {
      const color = getCellColor(2.0, 'cyan');
      expect(color).toBe('rgba(0, 212, 255, 1)');
    });

    it('clamps values below 0.0 to min intensity', () => {
      const color = getCellColor(-1.0, 'cyan');
      expect(color).toBe('rgba(0, 212, 255, 0.1)');
    });

    it('returns thermal colors for thermal scale', () => {
      const color = getCellColor(0.5, 'thermal');
      // At 0.5, thermal scale transitions — just verify it's not cyan
      expect(color).not.toContain('212, 255');
    });
  });
});
