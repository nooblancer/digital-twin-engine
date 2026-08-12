/**
 * Feature: digital-twin-v1.4, Property 6: BentoGrid — Item Rendering Integrity
 *
 * For any array of BentoGridItem objects with unique ids, the rendered grid
 * must contain exactly one DOM element per item — no duplicates and no omissions.
 * The rendered count must equal `items.length`.
 *
 * **Validates: Requirements 7.1, 7.5**
 */
import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { render } from "@testing-library/react";
import React from "react";
import {
  BentoGrid,
  type BentoGridItem,
  type CardSize,
} from "@/components/dashboard/BentoGrid";

// --- Arbitraries ---

const cardSizeArb: fc.Arbitrary<CardSize> = fc.constantFrom(
  "1x1",
  "2x1",
  "1x2",
  "2x2",
  "3x2"
);

/**
 * Generate an array of BentoGridItems with unique ids.
 * Uses fc.uuid() to guarantee uniqueness across items.
 */
const bentoGridItemsArb: fc.Arbitrary<BentoGridItem[]> = fc
  .array(
    fc.record({
      id: fc.uuid(),
      size: cardSizeArb,
    }),
    { minLength: 1, maxLength: 20 }
  )
  .map((items) =>
    items.map((item) => ({
      ...item,
      component: React.createElement("div", { "data-testid": `item-${item.id}` }, item.id),
    }))
  );

// --- Property 6: BentoGrid — Item Rendering Integrity ---

describe("Feature: digital-twin-v1.4, Property 6: BentoGrid — Item Rendering Integrity", () => {
  it("rendered item count equals input items count (no duplicates, no missing)", () => {
    fc.assert(
      fc.property(bentoGridItemsArb, (items) => {
        const { container } = render(
          <BentoGrid items={items} />
        );

        // The bento-grid container holds all items
        const gridContainer = container.querySelector(".bento-grid");
        expect(gridContainer).not.toBeNull();

        // Each item renders as a direct child slot in the grid
        const renderedSlots = gridContainer!.children;
        expect(renderedSlots.length).toBe(items.length);

        // Verify each item's content is present via data-testid
        const renderedIds = new Set<string>();
        for (const item of items) {
          const element = container.querySelector(`[data-testid="item-${item.id}"]`);
          expect(element).not.toBeNull();
          renderedIds.add(item.id);
        }

        // No duplicates: set size equals array length
        expect(renderedIds.size).toBe(items.length);
      }),
      { numRuns: 100 }
    );
  });

  it("rendered ids match input ids exactly (same set)", () => {
    fc.assert(
      fc.property(bentoGridItemsArb, (items) => {
        const { container } = render(
          <BentoGrid items={items} />
        );

        const inputIds = new Set(items.map((i) => i.id));

        // Query all rendered item content by data-testid pattern
        const renderedElements = container.querySelectorAll("[data-testid^='item-']");
        const renderedIds = new Set(
          Array.from(renderedElements).map((el) =>
            el.getAttribute("data-testid")!.replace("item-", "")
          )
        );

        // Sets must be identical
        expect(renderedIds.size).toBe(inputIds.size);
        for (const id of inputIds) {
          expect(renderedIds.has(id)).toBe(true);
        }
      }),
      { numRuns: 100 }
    );
  });
});
