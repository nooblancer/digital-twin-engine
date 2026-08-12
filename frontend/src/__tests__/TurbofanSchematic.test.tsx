/**
 * Unit tests for TurbofanSchematic component.
 *
 * Tests:
 * - SVG renders all 7 subsystem groups (fan, lpc, hpc, combustor, hpt, lpt, nozzle)
 * - Click on subsystem expands detail panel
 * - ARIA labels are present on each subsystem region
 * - NO WebGL/Three.js references — SVG-only implementation
 *
 * Requirements: 10.1, 10.5, 10.6, 10.7
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import React from "react";

// --- Mock framer-motion ---
vi.mock("framer-motion", () => ({
  motion: {
    div: ({
      children,
      className,
      role,
      "aria-label": ariaLabel,
      "data-testid": testId,
      ...rest
    }: Record<string, unknown>) => (
      <div
        className={className as string}
        role={role as string}
        aria-label={ariaLabel as string}
        data-testid={testId as string}
      >
        {children as React.ReactNode}
      </div>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

// --- Import component AFTER mocks ---
import {
  TurbofanSchematic,
  SubsystemHealthData,
} from "@/components/engine/TurbofanSchematic";

// ---------------------------------------------------------------------------
// Test Data
// ---------------------------------------------------------------------------

const ALL_SUBSYSTEM_IDS = [
  "fan",
  "lpc",
  "hpc",
  "combustor",
  "hpt",
  "lpt",
  "nozzle",
] as const;

function createHealthySubsystems(): SubsystemHealthData[] {
  return [
    {
      id: "fan",
      name: "Fan",
      healthIndex: 0.95,
      sensors: [
        { name: "fan_inlet_temp", value: 288.5, unit: "K" },
        { name: "fan_speed", value: 2400, unit: "rpm" },
      ],
    },
    {
      id: "lpc",
      name: "Low Pressure Compressor",
      healthIndex: 0.88,
      sensors: [{ name: "lpc_outlet_pressure", value: 152.3, unit: "kPa" }],
    },
    {
      id: "hpc",
      name: "High Pressure Compressor",
      healthIndex: 0.72,
      sensors: [
        { name: "hpc_outlet_temp", value: 620.1, unit: "K" },
        { name: "hpc_pressure_ratio", value: 14.2, unit: "" },
      ],
    },
    {
      id: "combustor",
      name: "Combustor",
      healthIndex: 0.55,
      sensors: [{ name: "combustor_exit_temp", value: 1450, unit: "K" }],
    },
    {
      id: "hpt",
      name: "High Pressure Turbine",
      healthIndex: 0.35,
      sensors: [{ name: "hpt_efficiency", value: 0.82, unit: "" }],
    },
    {
      id: "lpt",
      name: "Low Pressure Turbine",
      healthIndex: 0.9,
      sensors: [{ name: "lpt_outlet_temp", value: 780, unit: "K" }],
    },
    {
      id: "nozzle",
      name: "Nozzle",
      healthIndex: 0.97,
      sensors: [{ name: "exhaust_gas_temp", value: 620, unit: "K" }],
    },
  ];
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TurbofanSchematic", () => {
  afterEach(() => {
    cleanup();
  });

  describe("SVG renders all 7 subsystem groups (Requirement 10.1)", () => {
    it("renders all 7 subsystem regions as identifiable SVG groups", () => {
      const subsystems = createHealthySubsystems();
      render(<TurbofanSchematic subsystems={subsystems} />);

      for (const id of ALL_SUBSYSTEM_IDS) {
        const group = screen.getByTestId(`subsystem-${id}`);
        expect(group).toBeInTheDocument();
      }
    });

    it("renders exactly 7 subsystem groups — no more, no less", () => {
      const subsystems = createHealthySubsystems();
      const { container } = render(
        <TurbofanSchematic subsystems={subsystems} />
      );

      const groups = container.querySelectorAll('[data-testid^="subsystem-"]');
      expect(groups).toHaveLength(7);
    });

    it("renders SVG element with correct viewBox", () => {
      const subsystems = createHealthySubsystems();
      const { container } = render(
        <TurbofanSchematic subsystems={subsystems} />
      );

      const svg = container.querySelector("svg");
      expect(svg).toBeInTheDocument();
      expect(svg).toHaveAttribute("viewBox", "0 0 800 400");
      expect(svg).toHaveAttribute("preserveAspectRatio", "xMidYMid meet");
    });

    it("renders glow filter defs for healthy, warning, and critical states", () => {
      const subsystems = createHealthySubsystems();
      const { container } = render(
        <TurbofanSchematic subsystems={subsystems} />
      );

      const glowHealthy = container.querySelector("#glow-healthy");
      const glowWarning = container.querySelector("#glow-warning");
      const glowCritical = container.querySelector("#glow-critical");

      expect(glowHealthy).toBeInTheDocument();
      expect(glowWarning).toBeInTheDocument();
      expect(glowCritical).toBeInTheDocument();
    });

    it("applies correct glow filter based on health index", () => {
      const subsystems = createHealthySubsystems();
      const { container } = render(
        <TurbofanSchematic subsystems={subsystems} />
      );

      // Fan (0.95 > 0.7) → glow-healthy
      const fan = container.querySelector('[data-testid="subsystem-fan"]');
      expect(fan).toHaveAttribute("filter", "url(#glow-healthy)");

      // Combustor (0.55, between 0.4 and 0.7) → glow-warning
      const combustor = container.querySelector(
        '[data-testid="subsystem-combustor"]'
      );
      expect(combustor).toHaveAttribute("filter", "url(#glow-warning)");

      // HPT (0.35 ≤ 0.4) → glow-critical
      const hpt = container.querySelector('[data-testid="subsystem-hpt"]');
      expect(hpt).toHaveAttribute("filter", "url(#glow-critical)");
    });
  });

  describe("click expands detail panel (Requirement 10.5)", () => {
    it("shows detail panel when a subsystem is clicked", () => {
      const subsystems = createHealthySubsystems();
      render(<TurbofanSchematic subsystems={subsystems} />);

      const fanGroup = screen.getByTestId("subsystem-fan");
      fireEvent.click(fanGroup);

      const detailPanel = screen.getByTestId("subsystem-detail-panel");
      expect(detailPanel).toBeInTheDocument();
    });

    it("detail panel displays subsystem name and health", () => {
      const subsystems = createHealthySubsystems();
      render(<TurbofanSchematic subsystems={subsystems} />);

      const fanGroup = screen.getByTestId("subsystem-fan");
      fireEvent.click(fanGroup);

      const detailPanel = screen.getByTestId("subsystem-detail-panel");
      expect(detailPanel).toHaveTextContent("Fan");
      expect(detailPanel).toHaveTextContent("95%");
    });

    it("detail panel displays sensors for the clicked subsystem", () => {
      const subsystems = createHealthySubsystems();
      render(<TurbofanSchematic subsystems={subsystems} />);

      const fanGroup = screen.getByTestId("subsystem-fan");
      fireEvent.click(fanGroup);

      const detailPanel = screen.getByTestId("subsystem-detail-panel");
      expect(detailPanel).toHaveTextContent("fan_inlet_temp");
      expect(detailPanel).toHaveTextContent("288.50");
      expect(detailPanel).toHaveTextContent("K");
      expect(detailPanel).toHaveTextContent("fan_speed");
      expect(detailPanel).toHaveTextContent("2400.00");
      expect(detailPanel).toHaveTextContent("rpm");
    });

    it("clicking a different subsystem changes the detail panel", () => {
      const subsystems = createHealthySubsystems();
      render(<TurbofanSchematic subsystems={subsystems} />);

      // Click fan first
      fireEvent.click(screen.getByTestId("subsystem-fan"));
      expect(screen.getByTestId("subsystem-detail-panel")).toHaveTextContent(
        "Fan"
      );

      // Click combustor
      fireEvent.click(screen.getByTestId("subsystem-combustor"));
      expect(screen.getByTestId("subsystem-detail-panel")).toHaveTextContent(
        "Combustor"
      );
    });

    it("clicking the same subsystem again closes the panel", () => {
      const subsystems = createHealthySubsystems();
      render(<TurbofanSchematic subsystems={subsystems} />);

      const fanGroup = screen.getByTestId("subsystem-fan");
      fireEvent.click(fanGroup);
      expect(screen.getByTestId("subsystem-detail-panel")).toBeInTheDocument();

      // Click again to close
      fireEvent.click(fanGroup);
      expect(
        screen.queryByTestId("subsystem-detail-panel")
      ).not.toBeInTheDocument();
    });

    it("calls onSubsystemClick callback when a subsystem is clicked", () => {
      const subsystems = createHealthySubsystems();
      const onClickMock = vi.fn();
      render(
        <TurbofanSchematic
          subsystems={subsystems}
          onSubsystemClick={onClickMock}
        />
      );

      fireEvent.click(screen.getByTestId("subsystem-hpc"));
      expect(onClickMock).toHaveBeenCalledWith("hpc");
    });

    it("supports keyboard activation with Enter key", () => {
      const subsystems = createHealthySubsystems();
      render(<TurbofanSchematic subsystems={subsystems} />);

      const fanGroup = screen.getByTestId("subsystem-fan");
      fireEvent.keyDown(fanGroup, { key: "Enter" });

      expect(screen.getByTestId("subsystem-detail-panel")).toBeInTheDocument();
    });

    it("supports keyboard activation with Space key", () => {
      const subsystems = createHealthySubsystems();
      render(<TurbofanSchematic subsystems={subsystems} />);

      const lpcGroup = screen.getByTestId("subsystem-lpc");
      fireEvent.keyDown(lpcGroup, { key: " " });

      expect(screen.getByTestId("subsystem-detail-panel")).toBeInTheDocument();
      expect(screen.getByTestId("subsystem-detail-panel")).toHaveTextContent(
        "Low Pressure Compressor"
      );
    });
  });

  describe("ARIA labels present (Requirement 10.6)", () => {
    it("each subsystem group has role=button", () => {
      const subsystems = createHealthySubsystems();
      const { container } = render(
        <TurbofanSchematic subsystems={subsystems} />
      );

      for (const id of ALL_SUBSYSTEM_IDS) {
        const group = container.querySelector(`[data-testid="subsystem-${id}"]`);
        expect(group).toHaveAttribute("role", "button");
      }
    });

    it("each subsystem group has a descriptive aria-label with name and health", () => {
      const subsystems = createHealthySubsystems();
      const { container } = render(
        <TurbofanSchematic subsystems={subsystems} />
      );

      // Fan: healthy, health 95%
      const fan = container.querySelector('[data-testid="subsystem-fan"]');
      expect(fan?.getAttribute("aria-label")).toContain("Fan");
      expect(fan?.getAttribute("aria-label")).toContain("95%");

      // HPT: critical, health 35%
      const hpt = container.querySelector('[data-testid="subsystem-hpt"]');
      expect(hpt?.getAttribute("aria-label")).toContain("HPT");
      expect(hpt?.getAttribute("aria-label")).toContain("35%");
      expect(hpt?.getAttribute("aria-label")).toContain("critical");
    });

    it("each subsystem group has tabIndex=0 for keyboard access", () => {
      const subsystems = createHealthySubsystems();
      const { container } = render(
        <TurbofanSchematic subsystems={subsystems} />
      );

      for (const id of ALL_SUBSYSTEM_IDS) {
        const group = container.querySelector(`[data-testid="subsystem-${id}"]`);
        expect(group).toHaveAttribute("tabindex", "0");
      }
    });

    it("selected subsystem has aria-expanded=true", () => {
      const subsystems = createHealthySubsystems();
      const { container } = render(
        <TurbofanSchematic subsystems={subsystems} />
      );

      const fan = container.querySelector('[data-testid="subsystem-fan"]');
      // Initially not expanded
      expect(fan).toHaveAttribute("aria-expanded", "false");

      // Click to expand
      fireEvent.click(fan!);
      expect(fan).toHaveAttribute("aria-expanded", "true");
    });

    it("detail panel has role=region with accessible label", () => {
      const subsystems = createHealthySubsystems();
      render(<TurbofanSchematic subsystems={subsystems} />);

      fireEvent.click(screen.getByTestId("subsystem-fan"));

      const panel = screen.getByTestId("subsystem-detail-panel");
      expect(panel).toHaveAttribute("role", "region");
      expect(panel).toHaveAttribute("aria-label", "Fan detail panel");
    });

    it("SVG root has role=img with descriptive aria-label", () => {
      const subsystems = createHealthySubsystems();
      const { container } = render(
        <TurbofanSchematic subsystems={subsystems} />
      );

      const svg = container.querySelector("svg");
      expect(svg).toHaveAttribute("role", "img");
      expect(svg?.getAttribute("aria-label")).toContain("turbofan");
    });

    it("provides screen-reader-only list of all subsystem health", () => {
      const subsystems = createHealthySubsystems();
      const { container } = render(
        <TurbofanSchematic subsystems={subsystems} />
      );

      const srList = container.querySelector("ul.sr-only");
      expect(srList).toBeInTheDocument();
      expect(srList?.querySelectorAll("li")).toHaveLength(7);
    });
  });

  describe("NO WebGL references (Requirement 10.7)", () => {
    it("component does not reference WebGL, Three.js, or canvas", () => {
      const subsystems = createHealthySubsystems();
      const { container } = render(
        <TurbofanSchematic subsystems={subsystems} />
      );

      const html = container.innerHTML;
      expect(html).not.toContain("webgl");
      expect(html).not.toContain("WebGL");
      expect(html).not.toContain("three.js");
      expect(html).not.toContain("Three.js");
      expect(html).not.toContain("THREE");
      // Should not contain canvas elements
      expect(container.querySelector("canvas")).toBeNull();
    });

    it("renders using SVG elements exclusively", () => {
      const subsystems = createHealthySubsystems();
      const { container } = render(
        <TurbofanSchematic subsystems={subsystems} />
      );

      // Must have SVG
      const svg = container.querySelector("svg");
      expect(svg).toBeInTheDocument();

      // Must have SVG path elements for subsystem shapes
      const paths = svg?.querySelectorAll("path");
      expect(paths!.length).toBeGreaterThan(0);

      // Must have SVG filter elements for glow
      const filters = svg?.querySelectorAll("filter");
      expect(filters!.length).toBeGreaterThanOrEqual(3);
    });

    it("uses CSS filter (drop-shadow) for glow effects, not WebGL shaders", () => {
      const subsystems = createHealthySubsystems();
      const { container } = render(
        <TurbofanSchematic subsystems={subsystems} />
      );

      // Verify SVG filter elements contain drop-shadow definitions
      const svg = container.querySelector("svg");
      const svgHTML = svg!.innerHTML;
      // The feDropShadow elements are rendered (jsdom may lowercase them)
      expect(svgHTML.toLowerCase()).toContain("fedropshadow");
      // There should be at least 3 drop shadow filters (healthy, warning, critical)
      const matches = svgHTML.toLowerCase().match(/fedropshadow/g);
      expect(matches!.length).toBeGreaterThanOrEqual(3);
    });
  });

  describe("airflow animation (Requirement 10.4)", () => {
    it("renders animated airflow paths when showAirflow is true", () => {
      const subsystems = createHealthySubsystems();
      const { container } = render(
        <TurbofanSchematic subsystems={subsystems} showAirflow={true} />
      );

      const animateElements = container.querySelectorAll("animate");
      expect(animateElements.length).toBeGreaterThan(0);
    });

    it("does not render airflow paths when showAirflow is false", () => {
      const subsystems = createHealthySubsystems();
      const { container } = render(
        <TurbofanSchematic subsystems={subsystems} showAirflow={false} />
      );

      const animateElements = container.querySelectorAll("animate");
      expect(animateElements.length).toBe(0);
    });
  });

  describe("responsive and container fit (Requirement 10.6)", () => {
    it("SVG scales to fit container with preserveAspectRatio", () => {
      const subsystems = createHealthySubsystems();
      const { container } = render(
        <TurbofanSchematic subsystems={subsystems} />
      );

      const svg = container.querySelector("svg");
      expect(svg).toHaveAttribute("preserveAspectRatio", "xMidYMid meet");
      expect(svg?.classList.contains("w-full")).toBe(true);
    });

    it("accepts and applies custom className", () => {
      const subsystems = createHealthySubsystems();
      const { container } = render(
        <TurbofanSchematic
          subsystems={subsystems}
          className="custom-class max-w-4xl"
        />
      );

      const wrapper = container.querySelector(
        '[data-testid="turbofan-schematic"]'
      ) as HTMLElement;
      expect(wrapper.className).toContain("custom-class");
      expect(wrapper.className).toContain("max-w-4xl");
    });
  });
});
