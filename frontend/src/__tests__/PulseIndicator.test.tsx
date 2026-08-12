/**
 * Unit tests for PulseIndicator component.
 *
 * Tests:
 * - Renders correct color for each status (connected, disconnected, connecting)
 * - Applies correct ARIA attributes (role="status", aria-label)
 * - Renders correct size (sm=8px, md=12px, lg=16px)
 * - Applies pulse animation class when connected
 * - Does NOT apply animation class when disconnected
 * - Applies blink animation class when connecting
 *
 * Requirements: 8.3, 8.4, 8.6
 */
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { PulseIndicator } from "@/components/ui/PulseIndicator";

describe("PulseIndicator", () => {
  describe("ARIA attributes", () => {
    it('has role="status"', () => {
      const { container } = render(<PulseIndicator status="connected" />);
      const el = container.firstElementChild as HTMLElement;
      expect(el.getAttribute("role")).toBe("status");
    });

    it('has aria-label="Connection connected" when connected', () => {
      const { container } = render(<PulseIndicator status="connected" />);
      const el = container.firstElementChild as HTMLElement;
      expect(el.getAttribute("aria-label")).toBe("Connection connected");
    });

    it('has aria-label="Connection disconnected" when disconnected', () => {
      const { container } = render(<PulseIndicator status="disconnected" />);
      const el = container.firstElementChild as HTMLElement;
      expect(el.getAttribute("aria-label")).toBe("Connection disconnected");
    });

    it('has aria-label="Connection connecting" when connecting', () => {
      const { container } = render(<PulseIndicator status="connecting" />);
      const el = container.firstElementChild as HTMLElement;
      expect(el.getAttribute("aria-label")).toBe("Connection connecting");
    });
  });

  describe("size prop", () => {
    it("renders 8px for size sm", () => {
      const { container } = render(
        <PulseIndicator status="connected" size="sm" />
      );
      const el = container.firstElementChild as HTMLElement;
      expect(el.style.width).toBe("8px");
      expect(el.style.height).toBe("8px");
    });

    it("renders 12px for size md (default)", () => {
      const { container } = render(<PulseIndicator status="connected" />);
      const el = container.firstElementChild as HTMLElement;
      expect(el.style.width).toBe("12px");
      expect(el.style.height).toBe("12px");
    });

    it("renders 16px for size lg", () => {
      const { container } = render(
        <PulseIndicator status="connected" size="lg" />
      );
      const el = container.firstElementChild as HTMLElement;
      expect(el.style.width).toBe("16px");
      expect(el.style.height).toBe("16px");
    });
  });

  describe("status visual states", () => {
    it("connected: green background + pulse animation class", () => {
      const { container } = render(<PulseIndicator status="connected" />);
      const el = container.firstElementChild as HTMLElement;
      expect(el.className).toContain("bg-[#10b981]");
      expect(el.className).toContain("pulse-indicator-connected");
    });

    it("disconnected: red background, no animation class", () => {
      const { container } = render(<PulseIndicator status="disconnected" />);
      const el = container.firstElementChild as HTMLElement;
      expect(el.className).toContain("bg-[#ef4444]");
      expect(el.className).not.toContain("pulse-indicator-connected");
      expect(el.className).not.toContain("pulse-indicator-connecting");
    });

    it("connecting: amber background + blink animation class", () => {
      const { container } = render(<PulseIndicator status="connecting" />);
      const el = container.firstElementChild as HTMLElement;
      expect(el.className).toContain("bg-[#f59e0b]");
      expect(el.className).toContain("pulse-indicator-connecting");
    });
  });

  describe("className prop", () => {
    it("merges custom className", () => {
      const { container } = render(
        <PulseIndicator status="connected" className="ml-2" />
      );
      const el = container.firstElementChild as HTMLElement;
      expect(el.className).toContain("ml-2");
    });
  });
});
