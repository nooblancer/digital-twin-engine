/**
 * Unit tests for Fleet Overview page.
 *
 * Tests card rendering with known engine data, sort ordering by RUL ascending,
 * and navigation on card click.
 *
 * Requirements: 7.1, 7.2, 7.3
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within, fireEvent, cleanup } from '@testing-library/react';
import FleetOverviewPage from '@/app/fleet/page';
import type { EngineState } from '@/types/digital-twin';

// --- Mocks ---

const mockPush = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

vi.mock('@/hooks/useWebSocket', () => ({
  useWebSocket: vi.fn(),
}));

// We'll control the store state through a variable that the mock reads
let mockEngines: Record<number, EngineState> = {};

vi.mock('@/store', () => ({
  useStore: (selector: (state: { engines: Record<number, EngineState> }) => unknown) =>
    selector({ engines: mockEngines }),
}));

// --- Helpers ---

function createEngine(overrides: Partial<EngineState> & { engineId: number }): EngineState {
  return {
    rul: 100,
    healthIndex: 0.85,
    isProvisional: false,
    isUrgent: false,
    subsystems: [],
    trajectory: [],
    degradationRate: null,
    lastUpdateCycle: 50,
    ...overrides,
  };
}

// --- Tests ---

describe('Fleet Overview Page', () => {
  beforeEach(() => {
    mockEngines = {};
    mockPush.mockClear();
  });

  afterEach(() => {
    cleanup();
  });

  describe('Card rendering (Requirement 7.1)', () => {
    it('renders a card for each engine with unit ID, health index, RUL, and badge', () => {
      mockEngines = {
        1: createEngine({ engineId: 1, rul: 80, healthIndex: 0.9 }),
        2: createEngine({ engineId: 2, rul: 45, healthIndex: 0.55 }),
        3: createEngine({ engineId: 3, rul: 10, healthIndex: 0.3, isUrgent: true }),
      };

      render(<FleetOverviewPage />);

      // All three engines should have cards via aria-label
      expect(screen.getByLabelText(/Engine 1 — nominal, 80 cycles remaining/)).toBeInTheDocument();
      expect(screen.getByLabelText(/Engine 2 — degraded, 45 cycles remaining/)).toBeInTheDocument();
      expect(screen.getByLabelText(/Engine 3 — critical, 10 cycles remaining/)).toBeInTheDocument();

      // RUL values displayed
      expect(screen.getByText('80')).toBeInTheDocument();
      expect(screen.getByText('45')).toBeInTheDocument();
      expect(screen.getByText('10')).toBeInTheDocument();

      // Classification badges
      expect(screen.getByText('Nominal')).toBeInTheDocument();
      expect(screen.getByText('Degraded')).toBeInTheDocument();
      expect(screen.getByText('Critical')).toBeInTheDocument();

      // Health index percentages
      expect(screen.getByText('90%')).toBeInTheDocument();
      expect(screen.getByText('55%')).toBeInTheDocument();
      expect(screen.getByText('30%')).toBeInTheDocument();
    });

    it('displays health index as percentage in each card', () => {
      mockEngines = {
        5: createEngine({ engineId: 5, healthIndex: 0.72 }),
      };

      render(<FleetOverviewPage />);

      expect(screen.getByText('72%')).toBeInTheDocument();
    });

    it('shows empty state when no engines are present', () => {
      mockEngines = {};

      render(<FleetOverviewPage />);

      expect(screen.getByText('No engines detected')).toBeInTheDocument();
    });

    it('shows provisional indicator when engine is provisional', () => {
      mockEngines = {
        4: createEngine({ engineId: 4, isProvisional: true }),
      };

      render(<FleetOverviewPage />);

      expect(screen.getByText(/Provisional/)).toBeInTheDocument();
    });
  });

  describe('Sort ordering (Requirement 7.2)', () => {
    it('sorts engine cards by RUL ascending (most urgent first)', () => {
      mockEngines = {
        1: createEngine({ engineId: 1, rul: 100, healthIndex: 0.9 }),
        2: createEngine({ engineId: 2, rul: 25, healthIndex: 0.5, isUrgent: true }),
        3: createEngine({ engineId: 3, rul: 50, healthIndex: 0.65 }),
      };

      render(<FleetOverviewPage />);

      const buttons = screen.getAllByRole('button');

      // Cards sorted by RUL ascending: engine 2 (25), engine 3 (50), engine 1 (100)
      expect(buttons[0]).toHaveAttribute('aria-label', expect.stringContaining('Engine 2'));
      expect(buttons[1]).toHaveAttribute('aria-label', expect.stringContaining('Engine 3'));
      expect(buttons[2]).toHaveAttribute('aria-label', expect.stringContaining('Engine 1'));
    });

    it('places the engine with lowest RUL first when engines have equal RUL values', () => {
      mockEngines = {
        10: createEngine({ engineId: 10, rul: 60, healthIndex: 0.8 }),
        20: createEngine({ engineId: 20, rul: 60, healthIndex: 0.75 }),
        30: createEngine({ engineId: 30, rul: 30, healthIndex: 0.5 }),
      };

      render(<FleetOverviewPage />);

      const buttons = screen.getAllByRole('button');

      // Engine 30 (RUL 30) should be first, engines 10 & 20 (RUL 60) come after
      expect(buttons[0]).toHaveAttribute('aria-label', expect.stringContaining('Engine 30'));
      expect(buttons[1]).toHaveAttribute('aria-label', expect.stringContaining('60 cycles remaining'));
      expect(buttons[2]).toHaveAttribute('aria-label', expect.stringContaining('60 cycles remaining'));
    });
  });

  describe('Navigation on card click (Requirement 7.3)', () => {
    it('navigates to /engine/[id] when a card is clicked', () => {
      mockEngines = {
        7: createEngine({ engineId: 7, rul: 55, healthIndex: 0.8 }),
      };

      render(<FleetOverviewPage />);

      const card = screen.getByRole('button', {
        name: /Engine 7 — nominal, 55 cycles remaining/,
      });
      fireEvent.click(card);

      expect(mockPush).toHaveBeenCalledWith('/engine/7');
    });

    it('navigates to the correct engine when multiple cards exist', () => {
      mockEngines = {
        1: createEngine({ engineId: 1, rul: 90, healthIndex: 0.85 }),
        2: createEngine({ engineId: 2, rul: 40, healthIndex: 0.6 }),
      };

      render(<FleetOverviewPage />);

      // Use exact aria-label match to avoid ambiguity
      const card = screen.getByRole('button', {
        name: /Engine 1 — nominal, 90 cycles remaining/,
      });
      fireEvent.click(card);

      expect(mockPush).toHaveBeenCalledWith('/engine/1');
    });

    it('clicking the most urgent engine navigates correctly', () => {
      mockEngines = {
        5: createEngine({ engineId: 5, rul: 120, healthIndex: 0.9 }),
        8: createEngine({ engineId: 8, rul: 15, healthIndex: 0.35, isUrgent: true }),
      };

      render(<FleetOverviewPage />);

      // Engine 8 is first (lowest RUL)
      const buttons = screen.getAllByRole('button');
      fireEvent.click(buttons[0]);

      expect(mockPush).toHaveBeenCalledWith('/engine/8');
    });
  });
});
