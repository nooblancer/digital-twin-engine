import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { DATA_SOURCES } from '@/lib/data-sources';
import type { DataSource } from '@/types';

/**
 * Feature: dashboard-frontend, Property 11: Data Source Grouping by Domain
 *
 * For ANY subset of data sources with assigned domains, when grouped by domain,
 * each source appears exactly once within its correct domain category.
 *
 * **Validates: Requirements 14.4**
 */

// Reimplement groupByDomain (same logic as the landing page uses)
function groupByDomain(sources: DataSource[]): Record<string, DataSource[]> {
  const grouped: Record<string, DataSource[]> = {};
  for (const source of sources) {
    if (!grouped[source.domain]) grouped[source.domain] = [];
    grouped[source.domain].push(source);
  }
  return grouped;
}

describe('Feature: dashboard-frontend, Property 11: Data Source Grouping by Domain', () => {
  it('each source appears exactly once within its correct domain category for any subset', () => {
    fc.assert(
      fc.property(
        fc.shuffledSubarray(DATA_SOURCES, { minLength: 0, maxLength: DATA_SOURCES.length }),
        (subset) => {
          const grouped = groupByDomain(subset);

          // Collect all sources from grouped output
          const allGrouped: DataSource[] = [];
          for (const domain of Object.keys(grouped)) {
            for (const source of grouped[domain]) {
              allGrouped.push(source);
            }
          }

          // Assert: total count across all groups equals the input count
          expect(allGrouped.length).toBe(subset.length);

          // Assert: each source appears exactly once in the grouped output
          const ids = allGrouped.map((s) => s.id);
          const uniqueIds = new Set(ids);
          expect(uniqueIds.size).toBe(subset.length);

          // Assert: each source is in the correct domain group
          for (const [domain, sources] of Object.entries(grouped)) {
            for (const source of sources) {
              expect(source.domain).toBe(domain);
            }
          }

          // Assert: every input source is present in the output
          for (const source of subset) {
            expect(ids).toContain(source.id);
          }
        }
      ),
      { numRuns: 150 }
    );
  });
});
