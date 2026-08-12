/**
 * Feature: digital-twin-v1.4, Property 8: TelemetryWaterfall — Buffer Size Bound
 *
 * No matter how many WebSocket data arrivals occur, the internal ring buffer
 * must never exceed VISIBLE_STEPS + 10 entries. Older entries are evicted as
 * new ones arrive. This prevents unbounded memory growth.
 *
 * **Validates: Requirements 11.3, 11.6**
 */
import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import {
  WaterfallRingBuffer,
  VISIBLE_STEPS,
  BUFFER_SIZE,
} from '@/components/visualizations/TelemetryWaterfall';

// --- Arbitraries ---

/**
 * Generate a column of 21 deviation values (one per sensor channel).
 * Each deviation is in [0.0, 1.0].
 */
const columnArb: fc.Arbitrary<number[]> = fc.array(
  fc.float({ min: 0, max: 1, noNaN: true }),
  { minLength: 21, maxLength: 21 }
);

/**
 * Generate an arbitrary number of data arrivals (columns to push).
 * Tests from 0 to 200 pushes to cover well beyond the buffer capacity.
 */
const dataPushesArb: fc.Arbitrary<number[][]> = fc.array(columnArb, {
  minLength: 0,
  maxLength: 200,
});

// --- Property 8: TelemetryWaterfall — Buffer Size Bound ---

describe('Feature: digital-twin-v1.4, Property 8: TelemetryWaterfall — Buffer Size Bound', () => {
  it('buffer.length ≤ VISIBLE_STEPS + 10 after any number of data arrivals', () => {
    fc.assert(
      fc.property(dataPushesArb, (columns) => {
        const buffer = new WaterfallRingBuffer(BUFFER_SIZE);

        // Push all columns into the buffer
        for (const column of columns) {
          buffer.push(column);
        }

        // Invariant: buffer length must never exceed VISIBLE_STEPS + 10
        expect(buffer.length).toBeLessThanOrEqual(VISIBLE_STEPS + 10);
        expect(buffer.length).toBeLessThanOrEqual(BUFFER_SIZE);
      }),
      { numRuns: 200 }
    );
  });

  it('buffer length equals min(pushCount, BUFFER_SIZE) for any push sequence', () => {
    fc.assert(
      fc.property(dataPushesArb, (columns) => {
        const buffer = new WaterfallRingBuffer(BUFFER_SIZE);

        for (const column of columns) {
          buffer.push(column);
        }

        // Length should be exactly min(total pushes, capacity)
        const expectedLength = Math.min(columns.length, BUFFER_SIZE);
        expect(buffer.length).toBe(expectedLength);
      }),
      { numRuns: 200 }
    );
  });

  it('buffer never exceeds capacity even with incremental pushes checked at every step', () => {
    fc.assert(
      fc.property(dataPushesArb, (columns) => {
        const buffer = new WaterfallRingBuffer(BUFFER_SIZE);

        // Check the invariant holds after EVERY push, not just at the end
        for (const column of columns) {
          buffer.push(column);
          expect(buffer.length).toBeLessThanOrEqual(VISIBLE_STEPS + 10);
        }
      }),
      { numRuns: 100 }
    );
  });
});
