/**
 * Tests for v1.3 component visual polish integration.
 *
 * Tests:
 * - GlowCard wrappers present around each simulation component
 * - Mission Control color tokens used (no hardcoded hex matching old values)
 * - BentoGrid spans applied correctly for simulation components
 *
 * Requirements: 18.1, 18.2, 18.6
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

// --- Mock fetch globally ---
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// --- Mock framer-motion ---
vi.mock('framer-motion', () => ({
  motion: {
    p: ({ children, className, ...rest }: Record<string, unknown>) => (
      <p data-testid="motion-p" className={className as string} {...rest}>
        {children as React.ReactNode}
      </p>
    ),
    div: ({ children, className, ...rest }: Record<string, unknown>) => (
      <div data-testid="motion-div" className={className as string} {...rest}>
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

// --- Mock Recharts ---
vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  AreaChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="area-chart">{children}</div>
  ),
  LineChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="line-chart">{children}</div>
  ),
  ComposedChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="composed-chart">{children}</div>
  ),
  Area: (props: Record<string, unknown>) => (
    <div data-testid={`area-${props.dataKey}`} />
  ),
  Line: (props: Record<string, unknown>) => (
    <div data-testid={`line-${props.dataKey}`} />
  ),
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  CartesianGrid: () => <div data-testid="cartesian-grid" />,
  Tooltip: () => <div data-testid="tooltip" />,
  ReferenceLine: () => <div data-testid="reference-line" />,
  Legend: () => <div data-testid="legend" />,
}));

// --- Import components AFTER mocks ---
import { FaultInjectionPanel } from '@/components/visualizations/FaultInjectionPanel';
import { WhatIfStressSlider } from '@/components/visualizations/WhatIfStressSlider';
import { MonteCarloFanChart } from '@/components/visualizations/MonteCarloFanChart';
import { DegradationCurveProjection } from '@/components/visualizations/DegradationCurveProjection';
import { RULCountdown } from '@/components/visualizations/RULCountdown';
import { BentoGrid } from '@/components/dashboard/BentoGrid';
import type { BentoGridItem } from '@/components/dashboard/BentoGrid';
import { act } from '@testing-library/react';

describe('v1.3 Component Visual Polish (Req 18.1, 18.2, 18.6)', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    // Default mock that returns empty arrays/success for API calls
    mockFetch.mockImplementation(async (url: string) => {
      if (url.includes('/snapshot')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ health: { cycle_count: 25 } }),
        };
      }
      if (url.includes('/active-faults')) {
        return {
          ok: true,
          status: 200,
          json: async () => ([]),
        };
      }
      // Default simulation result
      return {
        ok: true,
        status: 200,
        json: async () => ({
          percentiles: {
            5: Array(50).fill(0.3),
            25: Array(50).fill(0.5),
            50: Array(50).fill(0.6),
            75: Array(50).fill(0.7),
            95: Array(50).fill(0.85),
          },
          failure_probability_by_cycle: Array(50).fill(0.1),
          expected_rul: 42,
          confidence_interval_90: [35, 50],
        }),
        text: async () => '{}',
      };
    });
  });

  afterEach(() => {
    cleanup();
  });

  describe('GlowCard wrappers present around simulation components (Req 18.2)', () => {
    it('FaultInjectionPanel renders inside a GlowCard (bg-mission-surface-1)', async () => {
      let container: HTMLElement;
      await act(async () => {
        const result = render(<FaultInjectionPanel />);
        container = result.container;
      });

      // GlowCard renders a div with bg-mission-surface-1 as the outermost wrapper
      const glowCard = container!.querySelector('.bg-mission-surface-1');
      expect(glowCard).toBeInTheDocument();
      // Should also have the rounded-md border styling from GlowCard
      expect(glowCard!.className).toContain('rounded-md');
      expect(glowCard!.className).toContain('border');
    });

    it('WhatIfStressSlider renders inside a GlowCard', async () => {
      let container: HTMLElement;
      await act(async () => {
        const result = render(
          <WhatIfStressSlider engineId={1} onSimulationResult={vi.fn()} />
        );
        container = result.container;
      });

      const glowCard = container!.querySelector('.bg-mission-surface-1');
      expect(glowCard).toBeInTheDocument();
      expect(glowCard!.className).toContain('rounded-md');
      expect(glowCard!.className).toContain('border');
    });

    it('MonteCarloFanChart renders inside a GlowCard', () => {
      const { container } = render(
        <MonteCarloFanChart percentiles={null} />
      );

      const glowCard = container.querySelector('.bg-mission-surface-1');
      expect(glowCard).toBeInTheDocument();
      expect(glowCard!.className).toContain('rounded-md');
    });

    it('DegradationCurveProjection renders inside a GlowCard', () => {
      const { container } = render(
        <DegradationCurveProjection historicalData={[]} />
      );

      const glowCard = container.querySelector('.bg-mission-surface-1');
      expect(glowCard).toBeInTheDocument();
      expect(glowCard!.className).toContain('rounded-md');
    });

    it('RULCountdown renders inside a GlowCard', () => {
      const { container } = render(
        <RULCountdown expectedRul={42} confidenceInterval90={[35, 50]} />
      );

      const glowCard = container.querySelector('.bg-mission-surface-1');
      expect(glowCard).toBeInTheDocument();
      expect(glowCard!.className).toContain('rounded-md');
    });
  });

  describe('Mission Control color tokens used — no hardcoded old hex (Req 18.1)', () => {
    it('FaultInjectionPanel does not use hardcoded bg-[#12141a] or bg-[#1a1d27]', async () => {
      let container: HTMLElement;
      await act(async () => {
        const result = render(<FaultInjectionPanel />);
        container = result.container;
      });

      const html = container!.innerHTML;
      expect(html).not.toContain('bg-[#12141a]');
      expect(html).not.toContain('bg-[#1a1d27]');
    });

    it('FaultInjectionPanel uses Mission Control tokens (mission-cyan, mission-crimson)', async () => {
      let container: HTMLElement;
      await act(async () => {
        const result = render(<FaultInjectionPanel />);
        container = result.container;
      });

      const html = container!.innerHTML;
      // Should use mission-cyan for preset buttons
      expect(html).toContain('mission-cyan');
      // Should use mission-crimson for danger styling
      expect(html).toContain('mission-crimson');
    });

    it('WhatIfStressSlider does not use hardcoded bg-[#12141a] or bg-[#1a1d27]', async () => {
      let container: HTMLElement;
      await act(async () => {
        const result = render(
          <WhatIfStressSlider engineId={1} onSimulationResult={vi.fn()} />
        );
        container = result.container;
      });

      const html = container!.innerHTML;
      expect(html).not.toContain('bg-[#12141a]');
      expect(html).not.toContain('bg-[#1a1d27]');
    });

    it('MonteCarloFanChart does not use hardcoded bg-[#12141a] or bg-[#1a1d27]', () => {
      const { container } = render(
        <MonteCarloFanChart percentiles={null} />
      );

      const html = container.innerHTML;
      expect(html).not.toContain('bg-[#12141a]');
      expect(html).not.toContain('bg-[#1a1d27]');
    });

    it('DegradationCurveProjection does not use hardcoded bg-[#12141a] or bg-[#1a1d27]', () => {
      const { container } = render(
        <DegradationCurveProjection historicalData={[]} />
      );

      const html = container.innerHTML;
      expect(html).not.toContain('bg-[#12141a]');
      expect(html).not.toContain('bg-[#1a1d27]');
    });

    it('RULCountdown does not use hardcoded bg-[#12141a] or bg-[#1a1d27]', () => {
      const { container } = render(
        <RULCountdown expectedRul={42} confidenceInterval90={[35, 50]} />
      );

      const html = container.innerHTML;
      expect(html).not.toContain('bg-[#12141a]');
      expect(html).not.toContain('bg-[#1a1d27]');
    });

    it('all simulation components use bg-mission-surface-1 via GlowCard', () => {
      // Render each and verify the GlowCard token is present
      const { container: c1 } = render(
        <MonteCarloFanChart percentiles={null} />
      );
      expect(c1.querySelector('.bg-mission-surface-1')).toBeInTheDocument();
      cleanup();

      const { container: c2 } = render(
        <DegradationCurveProjection historicalData={[]} />
      );
      expect(c2.querySelector('.bg-mission-surface-1')).toBeInTheDocument();
      cleanup();

      const { container: c3 } = render(
        <RULCountdown expectedRul={42} confidenceInterval90={[35, 50]} />
      );
      expect(c3.querySelector('.bg-mission-surface-1')).toBeInTheDocument();
    });
  });

  describe('BentoGrid spans applied correctly for v1.3 components (Req 18.6)', () => {
    it('renders simulation components in BentoGrid with correct spans', () => {
      // Replicate the SimulationBentoSection layout from the engine page
      const items: BentoGridItem[] = [
        {
          id: 'rul-countdown',
          size: '1x1',
          component: <div data-testid="rul-slot">RUL</div>,
        },
        {
          id: 'what-if-slider',
          size: '2x1',
          component: <div data-testid="slider-slot">Slider</div>,
        },
        {
          id: 'fault-injection',
          size: '1x2',
          component: <div data-testid="fault-slot">Faults</div>,
        },
        {
          id: 'monte-carlo-fan',
          size: '2x2',
          component: <div data-testid="fan-slot">FanChart</div>,
        },
        {
          id: 'degradation-curve',
          size: '2x2',
          component: <div data-testid="degrade-slot">Degradation</div>,
        },
      ];

      const { container } = render(<BentoGrid items={items} />);
      const grid = container.firstElementChild as HTMLElement;
      const slots = Array.from(grid.children) as HTMLElement[];

      // Verify correct number of slots
      expect(slots).toHaveLength(5);

      // RULCountdown gets 1x1 span
      expect(slots[0].className).toContain('bento-1x1');
      expect(slots[0].querySelector('[data-testid="rul-slot"]')).toBeInTheDocument();

      // WhatIfStressSlider gets 2x1 span
      expect(slots[1].className).toContain('bento-2x1');
      expect(slots[1].querySelector('[data-testid="slider-slot"]')).toBeInTheDocument();

      // FaultInjectionPanel gets 1x2 span
      expect(slots[2].className).toContain('bento-1x2');
      expect(slots[2].querySelector('[data-testid="fault-slot"]')).toBeInTheDocument();

      // MonteCarloFanChart gets 2x2 span
      expect(slots[3].className).toContain('bento-2x2');
      expect(slots[3].querySelector('[data-testid="fan-slot"]')).toBeInTheDocument();

      // DegradationCurveProjection gets 2x2 span
      expect(slots[4].className).toContain('bento-2x2');
      expect(slots[4].querySelector('[data-testid="degrade-slot"]')).toBeInTheDocument();
    });

    it('BentoGrid container has bento-grid class for CSS grid rules', () => {
      const items: BentoGridItem[] = [
        { id: 'rul-countdown', size: '1x1', component: <div>RUL</div> },
        { id: 'what-if-slider', size: '2x1', component: <div>Slider</div> },
      ];

      const { container } = render(<BentoGrid items={items} />);
      const grid = container.firstElementChild as HTMLElement;
      expect(grid.className).toContain('bento-grid');
    });

    it('grid slots use overflow-hidden to prevent clipping outside cell', () => {
      const items: BentoGridItem[] = [
        { id: 'monte-carlo-fan', size: '2x2', component: <div>FanChart</div> },
        { id: 'degradation-curve', size: '2x2', component: <div>Degradation</div> },
      ];

      const { container } = render(<BentoGrid items={items} />);
      const grid = container.firstElementChild as HTMLElement;
      const slots = Array.from(grid.children) as HTMLElement[];

      slots.forEach((slot) => {
        expect(slot.className).toContain('overflow-hidden');
      });
    });
  });
});
