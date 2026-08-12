/**
 * Unit tests for BentoGrid component.
 *
 * Tests:
 * - Renders all items in the grid
 * - Applies correct bento span classes per card size
 * - Applies "bento-grid" class to container
 * - Responsive collapse: single column on viewports < 768px (CSS-level, verified via class presence)
 * - No layout shifts: overflow-hidden and contain:layout on slots
 * - Merges custom className on the grid container
 * - Handles empty items array gracefully
 *
 * Requirements: 7.1, 7.2, 7.4, 7.5
 */
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { BentoGrid, BentoGridItem, CardSize } from "@/components/dashboard/BentoGrid";

function makeItem(id: string, size: CardSize): BentoGridItem {
  return {
    id,
    size,
    component: <div data-testid={`item-${id}`}>{id}</div>,
  };
}

describe("BentoGrid", () => {
  describe("item rendering", () => {
    it("renders all items", () => {
      const items: BentoGridItem[] = [
        makeItem("a", "1x1"),
        makeItem("b", "2x1"),
        makeItem("c", "1x2"),
      ];

      const { getByTestId } = render(<BentoGrid items={items} />);

      expect(getByTestId("item-a")).toBeInTheDocument();
      expect(getByTestId("item-b")).toBeInTheDocument();
      expect(getByTestId("item-c")).toBeInTheDocument();
    });

    it("renders correct number of grid slots matching items length", () => {
      const items: BentoGridItem[] = [
        makeItem("1", "1x1"),
        makeItem("2", "2x2"),
        makeItem("3", "3x2"),
        makeItem("4", "1x1"),
        makeItem("5", "2x1"),
      ];

      const { container } = render(<BentoGrid items={items} />);
      const grid = container.firstElementChild as HTMLElement;
      expect(grid.children.length).toBe(5);
    });

    it("renders empty grid when items array is empty", () => {
      const { container } = render(<BentoGrid items={[]} />);
      const grid = container.firstElementChild as HTMLElement;
      expect(grid.children.length).toBe(0);
    });

    it("does not produce duplicate DOM elements for unique items", () => {
      const items: BentoGridItem[] = [
        makeItem("x", "1x1"),
        makeItem("y", "2x1"),
        makeItem("z", "2x2"),
      ];

      const { container } = render(<BentoGrid items={items} />);
      const grid = container.firstElementChild as HTMLElement;
      // Each item id should appear exactly once
      const ids = Array.from(grid.querySelectorAll("[data-testid]")).map(
        (el) => el.getAttribute("data-testid")
      );
      expect(ids).toEqual(["item-x", "item-y", "item-z"]);
    });
  });

  describe("grid span classes", () => {
    it("applies bento-1x1 class for 1x1 size", () => {
      const items = [makeItem("a", "1x1")];
      const { container } = render(<BentoGrid items={items} />);
      const slot = container.querySelector(".bento-1x1");
      expect(slot).toBeInTheDocument();
    });

    it("applies bento-2x1 class for 2x1 size", () => {
      const items = [makeItem("a", "2x1")];
      const { container } = render(<BentoGrid items={items} />);
      const slot = container.querySelector(".bento-2x1");
      expect(slot).toBeInTheDocument();
    });

    it("applies bento-1x2 class for 1x2 size", () => {
      const items = [makeItem("a", "1x2")];
      const { container } = render(<BentoGrid items={items} />);
      const slot = container.querySelector(".bento-1x2");
      expect(slot).toBeInTheDocument();
    });

    it("applies bento-2x2 class for 2x2 size", () => {
      const items = [makeItem("a", "2x2")];
      const { container } = render(<BentoGrid items={items} />);
      const slot = container.querySelector(".bento-2x2");
      expect(slot).toBeInTheDocument();
    });

    it("applies bento-3x2 class for 3x2 size", () => {
      const items = [makeItem("a", "3x2")];
      const { container } = render(<BentoGrid items={items} />);
      const slot = container.querySelector(".bento-3x2");
      expect(slot).toBeInTheDocument();
    });

    it("applies correct span class to each item based on its size", () => {
      const items: BentoGridItem[] = [
        makeItem("small", "1x1"),
        makeItem("wide", "2x1"),
        makeItem("tall", "1x2"),
        makeItem("large", "2x2"),
        makeItem("extra", "3x2"),
      ];

      const { container } = render(<BentoGrid items={items} />);
      const grid = container.firstElementChild as HTMLElement;
      const slots = Array.from(grid.children) as HTMLElement[];

      expect(slots[0].className).toContain("bento-1x1");
      expect(slots[1].className).toContain("bento-2x1");
      expect(slots[2].className).toContain("bento-1x2");
      expect(slots[3].className).toContain("bento-2x2");
      expect(slots[4].className).toContain("bento-3x2");
    });
  });

  describe("grid container", () => {
    it("applies bento-grid class to the container element", () => {
      const items = [makeItem("a", "1x1")];
      const { container } = render(<BentoGrid items={items} />);
      const grid = container.firstElementChild as HTMLElement;
      expect(grid.className).toContain("bento-grid");
    });

    it("merges custom className onto the grid container", () => {
      const items = [makeItem("a", "1x1")];
      const { container } = render(
        <BentoGrid items={items} className="my-custom p-8" />
      );
      const grid = container.firstElementChild as HTMLElement;
      expect(grid.className).toContain("bento-grid");
      expect(grid.className).toContain("my-custom");
      expect(grid.className).toContain("p-8");
    });
  });

  describe("layout stability (no layout shifts)", () => {
    it("applies overflow-hidden on each grid slot", () => {
      const items = [makeItem("a", "1x1"), makeItem("b", "2x2")];
      const { container } = render(<BentoGrid items={items} />);
      const grid = container.firstElementChild as HTMLElement;
      const slots = Array.from(grid.children) as HTMLElement[];

      slots.forEach((slot) => {
        expect(slot.className).toContain("overflow-hidden");
      });
    });

    it("applies contain:layout style on each grid slot", () => {
      const items = [makeItem("a", "1x1"), makeItem("b", "2x1")];
      const { container } = render(<BentoGrid items={items} />);
      const grid = container.firstElementChild as HTMLElement;
      const slots = Array.from(grid.children) as HTMLElement[];

      slots.forEach((slot) => {
        expect(slot.style.contain).toBe("layout");
      });
    });
  });

  describe("responsive collapse", () => {
    it("has bento-grid class which includes responsive CSS rules for < 768px", () => {
      // The responsive collapse is handled by CSS (media query in globals.css):
      //   @media (max-width: 768px) {
      //     .bento-grid { grid-template-columns: 1fr; grid-auto-rows: auto; }
      //     .bento-grid > * { grid-column: span 1 !important; grid-row: span 1 !important; }
      //   }
      // In jsdom we can only verify the class is applied; actual media query
      // behavior is a CSS concern verified in visual/integration tests.
      const items = [
        makeItem("a", "3x2"),
        makeItem("b", "2x2"),
        makeItem("c", "1x1"),
      ];

      const { container } = render(<BentoGrid items={items} />);
      const grid = container.firstElementChild as HTMLElement;
      // The grid has the class that triggers responsive collapse via CSS
      expect(grid.className).toContain("bento-grid");
      // All children are direct children of .bento-grid (targeted by > * selector)
      expect(grid.children.length).toBe(3);
      Array.from(grid.children).forEach((child) => {
        expect(child.parentElement).toBe(grid);
      });
    });
  });
});
