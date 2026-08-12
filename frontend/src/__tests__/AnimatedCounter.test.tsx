/**
 * Unit tests for AnimatedCounter component.
 *
 * Tests:
 * - Displays formatted value using default format (toLocaleString)
 * - Displays formatted value using custom format function
 * - Renders label when provided
 * - Does not render label when omitted
 * - Has aria-live="polite" and aria-atomic="true" for accessibility
 * - Respects prefers-reduced-motion: instant update without animation
 * - Merges custom className
 *
 * Requirements: 14.2, 14.4
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup, act } from "@testing-library/react";

// Track whether reduced motion is active for tests
let mockPrefersReducedMotion = false;

// --- Mock animations lib ---
vi.mock("@/lib/animations", () => ({
  usePrefersReducedMotion: () => mockPrefersReducedMotion,
  counterSpring: {
    type: "spring" as const,
    stiffness: 100,
    damping: 15,
    mass: 0.5,
  },
}));

// Track motion value changes to verify behavior
let latestMotionValue = 0;
let springOnChange: ((value: number) => void) | null = null;

// --- Mock framer-motion ---
vi.mock("framer-motion", () => {
  return {
    motion: {
      span: ({
        children,
        className,
        ...rest
      }: Record<string, unknown>) => (
        <span className={className as string} {...rest}>
          {children as React.ReactNode}
        </span>
      ),
    },
    useMotionValue: (initial: number) => {
      latestMotionValue = initial;
      return {
        get: () => latestMotionValue,
        set: (v: number) => {
          latestMotionValue = v;
          // In reduced motion mode, fire the transform immediately
          if (springOnChange) {
            springOnChange(v);
          }
        },
      };
    },
    useSpring: (motionValue: { get: () => number }) => {
      // Return an object that mimics a spring motion value
      return {
        get: () => motionValue.get(),
        set: (v: number) => motionValue.set(v),
      };
    },
    useTransform: (
      source: { get: () => number },
      transform: (v: number) => string
    ) => {
      // Return a subscribable that calls transform on the source value
      const listeners: Array<(value: string) => void> = [];
      springOnChange = (v: number) => {
        const formatted = transform(v);
        listeners.forEach((fn) => fn(formatted));
      };
      return {
        get: () => transform(source.get()),
        on: (event: string, callback: (value: string) => void) => {
          listeners.push(callback);
          // Fire immediately so initial state is correct
          callback(transform(source.get()));
          return () => {
            const idx = listeners.indexOf(callback);
            if (idx >= 0) listeners.splice(idx, 1);
          };
        },
      };
    },
  };
});

// Import component AFTER mocks
import { AnimatedCounter } from "@/components/ui/AnimatedCounter";

describe("AnimatedCounter", () => {
  afterEach(() => {
    mockPrefersReducedMotion = false;
    latestMotionValue = 0;
    springOnChange = null;
    cleanup();
  });

  describe("displays formatted value", () => {
    it("displays value using default format (rounded toLocaleString)", () => {
      const { container } = render(<AnimatedCounter value={1234} />);
      const span = container.querySelector("span.text-2xl") as HTMLElement;
      // Default format: Math.round(v).toLocaleString()
      expect(span.textContent).toBe("1,234");
    });

    it("displays value using custom format function", () => {
      const customFormat = (v: number) => `${v.toFixed(1)}%`;
      const { container } = render(
        <AnimatedCounter value={42.7} format={customFormat} />
      );
      const span = container.querySelector("span.text-2xl") as HTMLElement;
      expect(span.textContent).toBe("42.7%");
    });

    it("displays zero correctly", () => {
      const { container } = render(<AnimatedCounter value={0} />);
      const span = container.querySelector("span.text-2xl") as HTMLElement;
      expect(span.textContent).toBe("0");
    });

    it("displays large numbers with locale formatting", () => {
      const { container } = render(<AnimatedCounter value={1000000} />);
      const span = container.querySelector("span.text-2xl") as HTMLElement;
      // toLocaleString output is environment-dependent; verify it contains
      // the rounded number in some locale-formatted form (not raw "1000000")
      expect(span.textContent).toBe(
        Math.round(1000000).toLocaleString()
      );
    });
  });

  describe("label rendering", () => {
    it("renders label when provided", () => {
      const { getByText } = render(
        <AnimatedCounter value={42} label="Events" />
      );
      expect(getByText("Events")).toBeInTheDocument();
    });

    it("does not render label element when label is omitted", () => {
      const { container } = render(<AnimatedCounter value={42} />);
      const labelEl = container.querySelector("span.text-xs");
      expect(labelEl).toBeNull();
    });
  });

  describe("accessibility", () => {
    it('has aria-live="polite" on the counter span', () => {
      const { container } = render(<AnimatedCounter value={100} />);
      const span = container.querySelector("span.text-2xl") as HTMLElement;
      expect(span.getAttribute("aria-live")).toBe("polite");
    });

    it('has aria-atomic="true" on the counter span', () => {
      const { container } = render(<AnimatedCounter value={100} />);
      const span = container.querySelector("span.text-2xl") as HTMLElement;
      expect(span.getAttribute("aria-atomic")).toBe("true");
    });
  });

  describe("respects prefers-reduced-motion", () => {
    it("updates display immediately without spring animation when reduced motion is preferred", () => {
      mockPrefersReducedMotion = true;

      const { container, rerender } = render(<AnimatedCounter value={100} />);
      const span = container.querySelector("span.text-2xl") as HTMLElement;
      expect(span.textContent).toBe("100");

      // Update value — should immediately display new value without animation
      rerender(<AnimatedCounter value={200} />);
      expect(span.textContent).toBe("200");
    });

    it("format function is applied even with reduced motion", () => {
      mockPrefersReducedMotion = true;
      const customFormat = (v: number) => `$${Math.round(v)}`;

      const { container } = render(
        <AnimatedCounter value={500} format={customFormat} />
      );
      const span = container.querySelector("span.text-2xl") as HTMLElement;
      expect(span.textContent).toBe("$500");
    });
  });

  describe("className prop", () => {
    it("merges custom className on wrapper div", () => {
      const { container } = render(
        <AnimatedCounter value={42} className="custom-class mt-4" />
      );
      const wrapper = container.firstElementChild as HTMLElement;
      expect(wrapper.className).toContain("custom-class");
      expect(wrapper.className).toContain("mt-4");
    });

    it("preserves base flex styles", () => {
      const { container } = render(<AnimatedCounter value={42} />);
      const wrapper = container.firstElementChild as HTMLElement;
      expect(wrapper.className).toContain("flex");
      expect(wrapper.className).toContain("flex-col");
      expect(wrapper.className).toContain("items-center");
    });
  });
});
