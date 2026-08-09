import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { buildHistoryUrl, validateTimeRange } from '@/components/HistoricalTrendExplorer';

// Valid date arbitrary that never produces NaN dates
const validDateArb = fc.integer({
  min: new Date('2000-01-01').getTime(),
  max: new Date('2100-01-01').getTime(),
}).map((ms) => new Date(ms));

describe('Feature: dashboard-frontend, Property 8: History Query Time Validation', () => {
  /**
   * **Validates: Requirements 6.6**
   *
   * For ANY pair of timestamps (start, end), the Historical Trend Explorer
   * SHALL reject the query when start >= end (returns false),
   * and SHALL permit the query only when start < end (returns true).
   */
  it('rejects when start >= end, permits when start < end', () => {
    fc.assert(
      fc.property(validDateArb, validDateArb, (dateA, dateB) => {
        const startIso = dateA.toISOString();
        const endIso = dateB.toISOString();

        const result = validateTimeRange(startIso, endIso);

        if (dateA.getTime() >= dateB.getTime()) {
          // start >= end → must reject
          expect(result).toBe(false);
        } else {
          // start < end → must permit
          expect(result).toBe(true);
        }
      }),
      { numRuns: 200 },
    );
  });

  it('always rejects when start and end are the same timestamp', () => {
    fc.assert(
      fc.property(validDateArb, (date) => {
        const iso = date.toISOString();
        expect(validateTimeRange(iso, iso)).toBe(false);
      }),
      { numRuns: 100 },
    );
  });
});

describe('Feature: dashboard-frontend, Property 9: History API URL Construction', () => {
  /**
   * **Validates: Requirements 6.2**
   *
   * For ANY valid combination of sensor_id (non-empty), start timestamp,
   * end timestamp, limit (1-1000), and offset (0-10000), the constructed
   * API request URL SHALL contain the correct path and query parameters
   * with properly URL-encoded sensor_id.
   */

  const sensorIdArb = fc.string({ minLength: 1, maxLength: 50 }).filter((s) => s.trim().length > 0);
  const timestampArb = fc
    .integer({ min: new Date('2000-01-01').getTime(), max: new Date('2100-01-01').getTime() })
    .map((ms) => new Date(ms).toISOString());
  const limitArb = fc.integer({ min: 1, max: 1000 });
  const offsetArb = fc.integer({ min: 0, max: 10000 });
  const baseUrl = 'http://localhost:8000';

  it('contains correct path with encoded sensorId', () => {
    fc.assert(
      fc.property(sensorIdArb, timestampArb, timestampArb, limitArb, offsetArb, (sensorId, start, end, limit, offset) => {
        const url = buildHistoryUrl(baseUrl, sensorId, start, end, limit, offset);
        const encodedSensorId = encodeURIComponent(sensorId);

        expect(url).toContain(`/sensors/${encodedSensorId}/state/history?`);
      }),
      { numRuns: 150 },
    );
  });

  it('contains start query parameter', () => {
    fc.assert(
      fc.property(sensorIdArb, timestampArb, timestampArb, limitArb, offsetArb, (sensorId, start, end, limit, offset) => {
        const url = buildHistoryUrl(baseUrl, sensorId, start, end, limit, offset);
        const params = new URL(url).searchParams;

        expect(params.get('start')).toBe(start);
      }),
      { numRuns: 150 },
    );
  });

  it('contains end query parameter', () => {
    fc.assert(
      fc.property(sensorIdArb, timestampArb, timestampArb, limitArb, offsetArb, (sensorId, start, end, limit, offset) => {
        const url = buildHistoryUrl(baseUrl, sensorId, start, end, limit, offset);
        const params = new URL(url).searchParams;

        expect(params.get('end')).toBe(end);
      }),
      { numRuns: 150 },
    );
  });

  it('contains limit query parameter', () => {
    fc.assert(
      fc.property(sensorIdArb, timestampArb, timestampArb, limitArb, offsetArb, (sensorId, start, end, limit, offset) => {
        const url = buildHistoryUrl(baseUrl, sensorId, start, end, limit, offset);
        const params = new URL(url).searchParams;

        expect(params.get('limit')).toBe(String(limit));
      }),
      { numRuns: 150 },
    );
  });

  it('contains offset query parameter', () => {
    fc.assert(
      fc.property(sensorIdArb, timestampArb, timestampArb, limitArb, offsetArb, (sensorId, start, end, limit, offset) => {
        const url = buildHistoryUrl(baseUrl, sensorId, start, end, limit, offset);
        const params = new URL(url).searchParams;

        expect(params.get('offset')).toBe(String(offset));
      }),
      { numRuns: 150 },
    );
  });

  it('sensorId is properly URL-encoded in the path', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('sensor/001', 'sensor with spaces', 'special&chars=yes', 'path/to/sensor#1', 'encoded%20already'),
        timestampArb,
        timestampArb,
        limitArb,
        offsetArb,
        (sensorId, start, end, limit, offset) => {
          const url = buildHistoryUrl(baseUrl, sensorId, start, end, limit, offset);
          const encodedSensorId = encodeURIComponent(sensorId);

          // The URL should contain the encoded form, not the raw form (unless they happen to be the same)
          expect(url).toContain(`/sensors/${encodedSensorId}/state/history`);
          // The encoded sensor ID should not contain unencoded special chars in path
          expect(url.split('?')[0]).not.toContain(sensorId === encodedSensorId ? '\x00' : sensorId);
        },
      ),
      { numRuns: 100 },
    );
  });
});
