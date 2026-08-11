/**
 * Unit tests for RULCountdown component.
 *
 * Tests:
 * - Color changes at threshold boundaries (19→red, 20→amber, 40→amber, 41→green)
 * - Renders "--" placeholder when expectedRul is null
 * - Pulsing animation activates when RUL < 20
 * - Displays confidence interval margin
 *
 * Requirements: 11.1–11.7
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

// --- Mock framer-motion ---
// Capture animate props to verify pulsing behavior
interface CapturedMotionProps {
  animate?: Record<string, unknown>;
  transition?: Record<string, unknown>;
  className?: string;
  children?: React.ReactNode;
}

const capturedMotionProps: CapturedMotionProps[] = [];

vi.mock('framer-motion', () => ({
  motion: {
    p: ({ children, animate, transition, className, ...rest }: Record<string, unknown>) => {
      capturedMotionProps.push({
        animate: animate as Record<string, unknown>,
        transition: transition as Record<string, unknown>,
        className: className as string,
        children: children as React.ReactNode,
      });
      return (
        <p data-testid="motion-p" className={className as string} {...rest}>
          {children as React.ReactNode}
        </p>
      );
    },
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// --- Import component AFTER mocks ---
import { RULCountdown } from '@/components/visualizations/RULCountdown';

// --- Tests ---

describe('RULCountdown', () => {
  afterEach(() => {
    capturedMotionProps.length = 0;
    cleanup();
  });

  describe('renders "--" placeholder when expectedRul is null', () => {
    it('shows "--" text when no data available', () => {
      render(<RULCountdown expectedRul={null} confidenceInterval90={null} />);

      expect(screen.getByText('--')).toBeInTheDocument();
    });

    it('shows "Awaiting data" message when null', () => {
      render(<RULCountdown expectedRul={null} confidenceInterval90={null} />);

      expect(screen.getByText('Awaiting data')).toBeInTheDocument();
    });
  });

  describe('color changes at threshold boundaries', () => {
    it('RUL=19 → red (critical)', () => {
      render(<RULCountdown expectedRul={19} confidenceInterval90={null} />);

      const motionP = screen.getByTestId('motion-p');
      expect(motionP.className).toContain('text-red-500');
    });

    it('RUL=20 → amber (warning)', () => {
      render(<RULCountdown expectedRul={20} confidenceInterval90={null} />);

      const motionP = screen.getByTestId('motion-p');
      expect(motionP.className).toContain('text-amber-500');
    });

    it('RUL=40 → amber (warning)', () => {
      render(<RULCountdown expectedRul={40} confidenceInterval90={null} />);

      const motionP = screen.getByTestId('motion-p');
      expect(motionP.className).toContain('text-amber-500');
    });

    it('RUL=41 → green (nominal)', () => {
      render(<RULCountdown expectedRul={41} confidenceInterval90={null} />);

      const motionP = screen.getByTestId('motion-p');
      expect(motionP.className).toContain('text-emerald-500');
    });
  });

  describe('pulsing animation activates when RUL < 20', () => {
    it('RUL=19 triggers pulsing scale animation', () => {
      render(<RULCountdown expectedRul={19} confidenceInterval90={null} />);

      // When critical (RUL < 20), the animate prop should include scale array [1, 1.05, 1]
      const criticalMotion = capturedMotionProps.find(
        (p) => p.className?.includes('text-red-500')
      );
      expect(criticalMotion).toBeDefined();
      expect(criticalMotion!.animate).toBeDefined();

      const animate = criticalMotion!.animate!;
      // Should have scale as array for pulsing
      expect(animate.scale).toEqual([1, 1.05, 1]);
    });

    it('RUL=19 has repeating transition for scale', () => {
      render(<RULCountdown expectedRul={19} confidenceInterval90={null} />);

      const criticalMotion = capturedMotionProps.find(
        (p) => p.className?.includes('text-red-500')
      );
      expect(criticalMotion).toBeDefined();
      expect(criticalMotion!.transition).toBeDefined();

      const transition = criticalMotion!.transition!;
      // Scale transition should repeat infinitely
      expect(transition.scale).toBeDefined();
      expect((transition.scale as Record<string, unknown>).repeat).toBe(Infinity);
    });

    it('RUL=41 does NOT trigger pulsing animation', () => {
      render(<RULCountdown expectedRul={41} confidenceInterval90={null} />);

      const nominalMotion = capturedMotionProps.find(
        (p) => p.className?.includes('text-emerald-500')
      );
      expect(nominalMotion).toBeDefined();

      const animate = nominalMotion!.animate!;
      // Should NOT have scale as array — just a fixed scale of 1
      expect(animate.scale).toBe(1);
    });

    it('RUL=20 does NOT trigger pulsing animation (boundary)', () => {
      render(<RULCountdown expectedRul={20} confidenceInterval90={null} />);

      const warningMotion = capturedMotionProps.find(
        (p) => p.className?.includes('text-amber-500')
      );
      expect(warningMotion).toBeDefined();

      const animate = warningMotion!.animate!;
      // 20 is not < 20, so no pulsing
      expect(animate.scale).toBe(1);
    });
  });

  describe('confidence interval display', () => {
    it('displays margin when confidence interval is provided', () => {
      render(
        <RULCountdown expectedRul={50} confidenceInterval90={[40, 60]} />
      );

      // margin = max(|50-40|, |60-50|) = 10
      expect(screen.getByText('± 10 cycles (90% CI)')).toBeInTheDocument();
    });

    it('does not display margin when confidence interval is null', () => {
      render(<RULCountdown expectedRul={50} confidenceInterval90={null} />);

      expect(screen.queryByText(/± .* cycles/)).not.toBeInTheDocument();
    });
  });

  describe('border styling changes with RUL', () => {
    it('RUL < 20 has red glow border', () => {
      const { container } = render(
        <RULCountdown expectedRul={10} confidenceInterval90={null} />
      );

      const wrapper = container.firstElementChild as HTMLElement;
      expect(wrapper.className).toContain('border-red-500/50');
    });

    it('RUL=30 has amber glow border', () => {
      const { container } = render(
        <RULCountdown expectedRul={30} confidenceInterval90={null} />
      );

      const wrapper = container.firstElementChild as HTMLElement;
      expect(wrapper.className).toContain('border-amber-500/30');
    });

    it('RUL=50 has default subtle border', () => {
      const { container } = render(
        <RULCountdown expectedRul={50} confidenceInterval90={null} />
      );

      const wrapper = container.firstElementChild as HTMLElement;
      expect(wrapper.className).toContain('border-white/[0.06]');
    });
  });
});
