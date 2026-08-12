/**
 * Unit tests for GlowCard component.
 *
 * Tests:
 * - Renders children correctly
 * - Applies correct glow color class when isActive is true
 * - Does NOT apply glow class when isActive is false
 * - Triggers glow-pulse animation class on false→true isActive transition
 * - Removes glow-pulse class after animation duration (400ms)
 * - Applies base styles (bg-mission-surface-1, rounded-md, border)
 * - Merges custom className
 * - Does not apply glow when glowColor is "none"
 *
 * Requirements: 8.1, 8.2, 8.6
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, act } from "@testing-library/react";
import { GlowCard } from "@/components/ui/GlowCard";

describe("GlowCard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe("base rendering", () => {
    it("renders children", () => {
      const { getByText } = render(
        <GlowCard>
          <p>Test content</p>
        </GlowCard>
      );
      expect(getByText("Test content")).toBeInTheDocument();
    });

    it("applies base card styles", () => {
      const { container } = render(
        <GlowCard>
          <p>content</p>
        </GlowCard>
      );
      const el = container.firstElementChild as HTMLElement;
      expect(el.className).toContain("bg-mission-surface-1");
      expect(el.className).toContain("rounded-md");
      expect(el.className).toContain("border");
    });

    it("merges custom className", () => {
      const { container } = render(
        <GlowCard className="p-4 my-custom">
          <p>content</p>
        </GlowCard>
      );
      const el = container.firstElementChild as HTMLElement;
      expect(el.className).toContain("p-4");
      expect(el.className).toContain("my-custom");
    });
  });

  describe("glow color when active", () => {
    it("applies glow-cyan class when isActive=true and glowColor=cyan", () => {
      const { container } = render(
        <GlowCard isActive={true} glowColor="cyan">
          <p>content</p>
        </GlowCard>
      );
      const el = container.firstElementChild as HTMLElement;
      expect(el.className).toContain("glow-cyan");
    });

    it("applies glow-violet class when isActive=true and glowColor=violet", () => {
      const { container } = render(
        <GlowCard isActive={true} glowColor="violet">
          <p>content</p>
        </GlowCard>
      );
      const el = container.firstElementChild as HTMLElement;
      expect(el.className).toContain("glow-violet");
    });

    it("applies glow-emerald class when isActive=true and glowColor=emerald", () => {
      const { container } = render(
        <GlowCard isActive={true} glowColor="emerald">
          <p>content</p>
        </GlowCard>
      );
      const el = container.firstElementChild as HTMLElement;
      expect(el.className).toContain("glow-emerald");
    });

    it("does NOT apply glow class when glowColor is none", () => {
      const { container } = render(
        <GlowCard isActive={true} glowColor="none">
          <p>content</p>
        </GlowCard>
      );
      const el = container.firstElementChild as HTMLElement;
      expect(el.className).not.toContain("glow-cyan");
      expect(el.className).not.toContain("glow-violet");
      expect(el.className).not.toContain("glow-emerald");
    });

    it("does NOT apply glow class when isActive is false", () => {
      const { container } = render(
        <GlowCard isActive={false} glowColor="cyan">
          <p>content</p>
        </GlowCard>
      );
      const el = container.firstElementChild as HTMLElement;
      expect(el.className).not.toContain("glow-cyan");
    });
  });

  describe("pulse animation on isActive transition", () => {
    it("applies glow-pulse-cyan class on false→true transition", () => {
      const { container, rerender } = render(
        <GlowCard isActive={false} glowColor="cyan">
          <p>content</p>
        </GlowCard>
      );

      // Transition to active
      rerender(
        <GlowCard isActive={true} glowColor="cyan">
          <p>content</p>
        </GlowCard>
      );

      const el = container.firstElementChild as HTMLElement;
      expect(el.className).toContain("glow-pulse-cyan");
    });

    it("applies glow-pulse-violet class on false→true transition for violet", () => {
      const { container, rerender } = render(
        <GlowCard isActive={false} glowColor="violet">
          <p>content</p>
        </GlowCard>
      );

      rerender(
        <GlowCard isActive={true} glowColor="violet">
          <p>content</p>
        </GlowCard>
      );

      const el = container.firstElementChild as HTMLElement;
      expect(el.className).toContain("glow-pulse-violet");
    });

    it("removes glow-pulse class after 400ms animation duration", () => {
      const { container, rerender } = render(
        <GlowCard isActive={false} glowColor="cyan">
          <p>content</p>
        </GlowCard>
      );

      rerender(
        <GlowCard isActive={true} glowColor="cyan">
          <p>content</p>
        </GlowCard>
      );

      const el = container.firstElementChild as HTMLElement;
      expect(el.className).toContain("glow-pulse-cyan");

      // Advance timer past animation duration
      act(() => {
        vi.advanceTimersByTime(400);
      });

      expect(el.className).not.toContain("glow-pulse-cyan");
    });

    it("does NOT pulse when isActive starts as true (no transition)", () => {
      const { container } = render(
        <GlowCard isActive={true} glowColor="cyan">
          <p>content</p>
        </GlowCard>
      );
      const el = container.firstElementChild as HTMLElement;
      // No pulse class because there was no false→true transition
      expect(el.className).not.toContain("glow-pulse-cyan");
    });

    it("does NOT apply pulse class when glowColor is none even on transition", () => {
      const { container, rerender } = render(
        <GlowCard isActive={false} glowColor="none">
          <p>content</p>
        </GlowCard>
      );

      rerender(
        <GlowCard isActive={true} glowColor="none">
          <p>content</p>
        </GlowCard>
      );

      const el = container.firstElementChild as HTMLElement;
      expect(el.className).not.toContain("glow-pulse");
    });
  });
});
