import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { EngineSchematic } from '@/components/EngineSchematic';
import type { SubsystemState } from '@/types/digital-twin';

const SUBSYSTEM_IDS = ['fan', 'lpc', 'hpc', 'combustor', 'hpt', 'lpt'] as const;

function makeSubsystems(
  overrides: Partial<Record<string, Partial<SubsystemState>>> = {}
): SubsystemState[] {
  return SUBSYSTEM_IDS.map((id) => ({
    name: id,
    healthScore: 0.85,
    classification: 'nominal' as const,
    ...overrides[id],
  }));
}

describe('Engine Schematic View', () => {
  afterEach(() => {
    cleanup();
  });

  describe('SVG rendering with known subsystem states', () => {
    it('renders all 6 subsystem regions', () => {
      render(<EngineSchematic subsystems={makeSubsystems()} />);

      for (const id of SUBSYSTEM_IDS) {
        expect(screen.getByTestId(`subsystem-${id}`)).toBeInTheDocument();
      }
    });

    it('renders an SVG element within the component', () => {
      const { container } = render(<EngineSchematic subsystems={makeSubsystems()} />);
      const svg = container.querySelector('svg');
      expect(svg).toBeInTheDocument();
      expect(svg).toHaveAttribute('viewBox', '0 0 800 400');
    });

    it('renders text labels for each subsystem', () => {
      render(<EngineSchematic subsystems={makeSubsystems()} />);
      expect(screen.getByText('Fan')).toBeInTheDocument();
      expect(screen.getByText('LPC')).toBeInTheDocument();
      expect(screen.getByText('HPC')).toBeInTheDocument();
      expect(screen.getByText('Combustor')).toBeInTheDocument();
      expect(screen.getByText('HPT')).toBeInTheDocument();
      expect(screen.getByText('LPT')).toBeInTheDocument();
    });
  });

  describe('color mapping for each classification', () => {
    it('applies green (#22c55e) stroke/fill for nominal classification', () => {
      render(
        <EngineSchematic
          subsystems={makeSubsystems({ fan: { classification: 'nominal' } })}
        />
      );
      const region = screen.getByTestId('subsystem-fan');
      const path = region.querySelector('path');
      expect(path).toHaveAttribute('stroke', '#22c55e');
      expect(path).toHaveAttribute('fill', '#22c55e');
    });

    it('applies amber (#f59e0b) stroke/fill for degraded classification', () => {
      render(
        <EngineSchematic
          subsystems={makeSubsystems({ hpc: { classification: 'degraded', healthScore: 0.55 } })}
        />
      );
      const region = screen.getByTestId('subsystem-hpc');
      const path = region.querySelector('path');
      expect(path).toHaveAttribute('stroke', '#f59e0b');
      expect(path).toHaveAttribute('fill', '#f59e0b');
    });

    it('applies red (#ef4444) stroke/fill for critical classification', () => {
      render(
        <EngineSchematic
          subsystems={makeSubsystems({ hpt: { classification: 'critical', healthScore: 0.2 } })}
        />
      );
      const region = screen.getByTestId('subsystem-hpt');
      const path = region.querySelector('path');
      expect(path).toHaveAttribute('stroke', '#ef4444');
      expect(path).toHaveAttribute('fill', '#ef4444');
    });

    it('applies grey (#9ca3af) stroke/fill for unknown classification', () => {
      render(
        <EngineSchematic
          subsystems={makeSubsystems({ lpt: { classification: 'unknown', healthScore: 0 } })}
        />
      );
      const region = screen.getByTestId('subsystem-lpt');
      const path = region.querySelector('path');
      expect(path).toHaveAttribute('stroke', '#9ca3af');
      expect(path).toHaveAttribute('fill', '#9ca3af');
    });

    it('shows correct classification indicators (✓/⚠/✗/?)', () => {
      const subsystems = makeSubsystems({
        fan: { classification: 'nominal' },
        lpc: { classification: 'degraded', healthScore: 0.5 },
        hpc: { classification: 'critical', healthScore: 0.2 },
        combustor: { classification: 'unknown', healthScore: 0 },
      });
      render(<EngineSchematic subsystems={subsystems} />);

      const fanRegion = screen.getByTestId('subsystem-fan');
      expect(fanRegion.textContent).toContain('✓');

      const lpcRegion = screen.getByTestId('subsystem-lpc');
      expect(lpcRegion.textContent).toContain('⚠');

      const hpcRegion = screen.getByTestId('subsystem-hpc');
      expect(hpcRegion.textContent).toContain('✗');

      const combustorRegion = screen.getByTestId('subsystem-combustor');
      expect(combustorRegion.textContent).toContain('?');
    });
  });

  describe('tooltip content', () => {
    it('shows tooltip on hover with subsystem name, health score (2dp), and classification', () => {
      const subsystems = makeSubsystems({
        fan: { healthScore: 0.87, classification: 'nominal' },
      });
      render(<EngineSchematic subsystems={subsystems} />);

      const fanRegion = screen.getByTestId('subsystem-fan');
      fireEvent.mouseEnter(fanRegion);

      const tooltip = screen.getByTestId('schematic-tooltip');
      expect(tooltip).toBeInTheDocument();
      expect(tooltip.textContent).toContain('Fan');
      expect(tooltip.textContent).toContain('0.87');
      expect(tooltip.textContent).toContain('nominal');
    });

    it('hides tooltip on mouse leave', () => {
      const subsystems = makeSubsystems({
        hpc: { healthScore: 0.55, classification: 'degraded' },
      });
      render(<EngineSchematic subsystems={subsystems} />);

      const hpcRegion = screen.getByTestId('subsystem-hpc');
      fireEvent.mouseEnter(hpcRegion);
      expect(screen.getByTestId('schematic-tooltip')).toBeInTheDocument();

      fireEvent.mouseLeave(hpcRegion);
      expect(screen.queryByTestId('schematic-tooltip')).not.toBeInTheDocument();
    });

    it('displays health score to exactly 2 decimal places in tooltip', () => {
      const subsystems = makeSubsystems({
        lpc: { healthScore: 0.7, classification: 'nominal' },
      });
      render(<EngineSchematic subsystems={subsystems} />);

      const lpcRegion = screen.getByTestId('subsystem-lpc');
      fireEvent.mouseEnter(lpcRegion);

      const tooltip = screen.getByTestId('schematic-tooltip');
      expect(tooltip.textContent).toContain('0.70');
    });
  });

  describe('accessibility labels', () => {
    it('has aria-label on each subsystem region with name, classification, and score', () => {
      const subsystems = makeSubsystems({
        fan: { healthScore: 0.92, classification: 'nominal' },
        hpc: { healthScore: 0.35, classification: 'critical' },
      });
      render(<EngineSchematic subsystems={subsystems} />);

      const fanRegion = screen.getByTestId('subsystem-fan');
      expect(fanRegion).toHaveAttribute(
        'aria-label',
        'Fan: nominal, health score 0.92'
      );

      const hpcRegion = screen.getByTestId('subsystem-hpc');
      expect(hpcRegion).toHaveAttribute(
        'aria-label',
        'HPC: critical, health score 0.35'
      );
    });

    it('has a top-level role="img" with descriptive aria-label', () => {
      render(<EngineSchematic subsystems={makeSubsystems()} />);
      const imgContainer = screen.getByRole('img');
      expect(imgContainer).toHaveAttribute(
        'aria-label',
        'Turbofan engine schematic showing subsystem health'
      );
    });

    it('includes a screen-reader-only list of subsystem health', () => {
      const subsystems = makeSubsystems({
        fan: { healthScore: 0.91, classification: 'nominal' },
      });
      const { container } = render(<EngineSchematic subsystems={subsystems} />);
      const srList = container.querySelector('ul.sr-only');
      expect(srList).toBeInTheDocument();
      expect(srList!.textContent).toContain('Fan: nominal, health score 0.91');
    });
  });

  describe('default grey state when no subsystems provided', () => {
    it('renders all regions in grey/unknown when subsystems array is empty', () => {
      render(<EngineSchematic subsystems={[]} />);

      for (const id of SUBSYSTEM_IDS) {
        const region = screen.getByTestId(`subsystem-${id}`);
        const path = region.querySelector('path');
        expect(path).toHaveAttribute('stroke', '#9ca3af');
        expect(path).toHaveAttribute('fill', '#9ca3af');
      }
    });

    it('shows "?" indicator for all regions when subsystems array is empty', () => {
      render(<EngineSchematic subsystems={[]} />);

      for (const id of SUBSYSTEM_IDS) {
        const region = screen.getByTestId(`subsystem-${id}`);
        expect(region.textContent).toContain('?');
      }
    });

    it('shows unknown classification in aria-labels when subsystems is empty', () => {
      render(<EngineSchematic subsystems={[]} />);

      const fanRegion = screen.getByTestId('subsystem-fan');
      expect(fanRegion.getAttribute('aria-label')).toContain('unknown');
    });
  });
});
