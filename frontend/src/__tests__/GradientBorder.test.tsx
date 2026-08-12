/**
 * Unit tests for GradientBorder component.
 *
 * Tests:
 * - Renders children correctly
 * - Applies default gradient background
 * - Accepts custom gradient prop
 * - Applies correct border width via padding
 * - Applies animation class when animated=true (default)
 * - Does NOT apply animation class when animated=false
 * - Has aria-hidden="true" on outer wrapper (decorative element)
 * - Renders inner content layer with bg-mission-surface-1
 * - Merges custom className on wrapper
 *
 * Requirements: 8.5, 8.6
 */
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { GradientBorder } from "@/components/ui/GradientBorder";

describe("GradientBorder", () => {
  describe("base rendering", () => {
    it("renders children", () => {
      const { getByText } = render(
        <GradientBorder>
          <p>Inner content</p>
        </GradientBorder>
      );
      expect(getByText("Inner content")).toBeInTheDocument();
    });

    it("renders outer wrapper with gradient-border-wrapper class", () => {
      const { container } = render(
        <GradientBorder>
          <p>content</p>
        </GradientBorder>
      );
      const wrapper = container.firstElementChild as HTMLElement;
      expect(wrapper.className).toContain("gradient-border-wrapper");
    });

    it("renders gradient background layer", () => {
      const { container } = render(
        <GradientBorder>
          <p>content</p>
        </GradientBorder>
      );
      const wrapper = container.firstElementChild as HTMLElement;
      const bgLayer = wrapper.querySelector(".gradient-border-bg") as HTMLElement;
      expect(bgLayer).not.toBeNull();
    });

    it("renders content layer with bg-mission-surface-1", () => {
      const { container } = render(
        <GradientBorder>
          <p>content</p>
        </GradientBorder>
      );
      const wrapper = container.firstElementChild as HTMLElement;
      const contentLayer = wrapper.querySelector(
        ".gradient-border-content"
      ) as HTMLElement;
      expect(contentLayer).not.toBeNull();
      expect(contentLayer.className).toContain("bg-mission-surface-1");
    });
  });

  describe("gradient prop", () => {
    it("applies default gradient when no gradient prop provided", () => {
      const { container } = render(
        <GradientBorder>
          <p>content</p>
        </GradientBorder>
      );
      const bgLayer = container.querySelector(
        ".gradient-border-bg"
      ) as HTMLElement;
      // Browser/JSDOM serializes hex to rgb format
      expect(bgLayer.style.background).toContain("linear-gradient(135deg");
      expect(bgLayer.style.background).toContain("rgb(0, 212, 255)");
      expect(bgLayer.style.background).toContain("rgb(124, 58, 237)");
      expect(bgLayer.style.background).toContain("rgb(16, 185, 129)");
    });

    it("applies custom gradient when prop is provided", () => {
      const customGradient = "linear-gradient(90deg, red, blue)";
      const { container } = render(
        <GradientBorder gradient={customGradient}>
          <p>content</p>
        </GradientBorder>
      );
      const bgLayer = container.querySelector(
        ".gradient-border-bg"
      ) as HTMLElement;
      expect(bgLayer.style.background).toContain(
        "linear-gradient(90deg, red, blue)"
      );
    });
  });

  describe("borderWidth prop", () => {
    it("applies default border width (1px padding)", () => {
      const { container } = render(
        <GradientBorder>
          <p>content</p>
        </GradientBorder>
      );
      const wrapper = container.firstElementChild as HTMLElement;
      expect(wrapper.style.padding).toBe("1px");
    });

    it("applies custom border width as padding", () => {
      const { container } = render(
        <GradientBorder borderWidth={3}>
          <p>content</p>
        </GradientBorder>
      );
      const wrapper = container.firstElementChild as HTMLElement;
      expect(wrapper.style.padding).toBe("3px");
    });
  });

  describe("animated prop", () => {
    it("applies gradient-border-animated class when animated=true (default)", () => {
      const { container } = render(
        <GradientBorder>
          <p>content</p>
        </GradientBorder>
      );
      const wrapper = container.firstElementChild as HTMLElement;
      expect(wrapper.className).toContain("gradient-border-animated");
    });

    it("does NOT apply gradient-border-animated class when animated=false", () => {
      const { container } = render(
        <GradientBorder animated={false}>
          <p>content</p>
        </GradientBorder>
      );
      const wrapper = container.firstElementChild as HTMLElement;
      expect(wrapper.className).not.toContain("gradient-border-animated");
    });
  });

  describe("accessibility", () => {
    it('has aria-hidden="true" on outer wrapper (decorative)', () => {
      const { container } = render(
        <GradientBorder>
          <p>content</p>
        </GradientBorder>
      );
      const wrapper = container.firstElementChild as HTMLElement;
      expect(wrapper.getAttribute("aria-hidden")).toBe("true");
    });
  });

  describe("className prop", () => {
    it("merges custom className on wrapper", () => {
      const { container } = render(
        <GradientBorder className="my-custom-class">
          <p>content</p>
        </GradientBorder>
      );
      const wrapper = container.firstElementChild as HTMLElement;
      expect(wrapper.className).toContain("my-custom-class");
    });
  });
});
