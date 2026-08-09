import { describe, it, expect } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';

const dashboardPath = path.resolve(__dirname, '../../../monitoring/grafana/dashboards/pipeline-metrics.json');
const dashboard = JSON.parse(fs.readFileSync(dashboardPath, 'utf-8'));

/**
 * Collect all panels from the dashboard, including those nested inside collapsed rows.
 */
function getAllPanels(): any[] {
  const panels: any[] = [];
  for (const panel of dashboard.panels) {
    panels.push(panel);
    if (panel.type === 'row' && Array.isArray(panel.panels)) {
      panels.push(...panel.panels);
    }
  }
  return panels;
}

/**
 * Get panels that belong to a specific row by title.
 * For non-collapsed rows, panels follow the row until the next row.
 * For collapsed rows, panels are nested inside the row's `panels` array.
 */
function getPanelsForRow(rowTitle: string): any[] {
  const allTopLevel = dashboard.panels;
  const rowIndex = allTopLevel.findIndex(
    (p: any) => p.type === 'row' && p.title === rowTitle
  );
  if (rowIndex === -1) return [];

  const row = allTopLevel[rowIndex];

  // Collapsed rows have nested panels
  if (row.collapsed && Array.isArray(row.panels)) {
    return row.panels;
  }

  // Non-collapsed rows: panels follow until the next row
  const panels: any[] = [];
  for (let i = rowIndex + 1; i < allTopLevel.length; i++) {
    if (allTopLevel[i].type === 'row') break;
    panels.push(allTopLevel[i]);
  }
  return panels;
}

/**
 * Collect all PromQL expr fields from all panels (including nested).
 */
function getAllExprs(): string[] {
  const exprs: string[] = [];
  const allPanels = getAllPanels();
  for (const panel of allPanels) {
    if (Array.isArray(panel.targets)) {
      for (const target of panel.targets) {
        if (target.expr !== undefined) {
          exprs.push(target.expr);
        }
      }
    }
  }
  return exprs;
}

/**
 * Collect all alert definitions from all panels (including nested).
 */
function getAllAlerts(): any[] {
  const alerts: any[] = [];
  const allPanels = getAllPanels();
  for (const panel of allPanels) {
    if (panel.alert) {
      alerts.push(panel.alert);
    }
  }
  return alerts;
}

describe('Grafana Dashboard JSON Validation', () => {
  describe('Expected panels exist per stage', () => {
    it('Ingestion row has Active Connections, Message Throughput, Buffer Utilization', () => {
      const panels = getPanelsForRow('Ingestion');
      const titles = panels.map((p: any) => p.title);
      expect(titles).toContain('Active Connections');
      expect(titles).toContain('Message Throughput');
      expect(titles).toContain('Buffer Utilization');
    });

    it('Broker row has Topic Throughput, Consumer Lag', () => {
      const panels = getPanelsForRow('Broker');
      const titles = panels.map((p: any) => p.title);
      expect(titles).toContain('Topic Throughput');
      expect(titles).toContain('Consumer Lag');
    });

    it('ML Service row has Predictions/s, Prediction Latency', () => {
      const panels = getPanelsForRow('ML Service');
      const titles = panels.map((p: any) => p.title);
      expect(titles).toContain('Predictions/s');
      expect(titles).toContain('Prediction Latency');
    });

    it('Correction Engine row has EnKF Iterations/s, Anomaly Detection Rate', () => {
      const panels = getPanelsForRow('Correction Engine');
      const titles = panels.map((p: any) => p.title);
      expect(titles).toContain('EnKF Iterations/s');
      expect(titles).toContain('Anomaly Detection Rate');
    });

    it('TSDB Writer row has Writes/s, Write Failure Count', () => {
      const panels = getPanelsForRow('TSDB Writer');
      const titles = panels.map((p: any) => p.title);
      expect(titles).toContain('Writes/s');
      expect(titles).toContain('Write Failure Count');
    });

    it('End-to-End row has Pipeline Latency (Ingestion to Corrected State)', () => {
      const panels = getPanelsForRow('End-to-End');
      const titles = panels.map((p: any) => p.title);
      expect(titles).toContain('Pipeline Latency (Ingestion to Corrected State)');
    });
  });

  describe('PromQL query targets are valid syntax', () => {
    it('all rate() calls have a range vector selector', () => {
      const exprs = getAllExprs();
      const rateExprs = exprs.filter((e) => e.includes('rate('));
      expect(rateExprs.length).toBeGreaterThan(0);

      for (const expr of rateExprs) {
        // rate() must contain a range vector like [1m], [5m], etc.
        expect(expr).toMatch(/rate\([^)]*\[\d+[smhd]\][^)]*\)/);
      }
    });

    it('all histogram_quantile() calls have a valid quantile (0-1) as first arg', () => {
      const exprs = getAllExprs();
      const hqExprs = exprs.filter((e) => e.includes('histogram_quantile('));
      expect(hqExprs.length).toBeGreaterThan(0);

      for (const expr of hqExprs) {
        const match = expr.match(/histogram_quantile\(\s*([\d.]+)/);
        expect(match).not.toBeNull();
        const quantile = parseFloat(match![1]);
        expect(quantile).toBeGreaterThanOrEqual(0);
        expect(quantile).toBeLessThanOrEqual(1);
      }
    });

    it('no empty expr fields exist', () => {
      const exprs = getAllExprs();
      expect(exprs.length).toBeGreaterThan(0);

      for (const expr of exprs) {
        expect(expr.trim()).not.toBe('');
      }
    });
  });

  describe('Alert rules are defined with correct thresholds', () => {
    it('High Consumer Lag alert exists with threshold > 5000', () => {
      const alerts = getAllAlerts();
      const alert = alerts.find((a) => a.name === 'High Consumer Lag');
      expect(alert).toBeDefined();

      const condition = alert.conditions[0];
      expect(condition.evaluator.type).toBe('gt');
      expect(condition.evaluator.params[0]).toBe(5000);
    });

    it('Slow Predictions alert exists with threshold > 0.2', () => {
      const alerts = getAllAlerts();
      const alert = alerts.find((a) => a.name === 'Slow Predictions');
      expect(alert).toBeDefined();

      const condition = alert.conditions[0];
      expect(condition.evaluator.type).toBe('gt');
      expect(condition.evaluator.params[0]).toBe(0.2);
    });

    it('TSDB Write Failures alert exists with threshold > 0', () => {
      const alerts = getAllAlerts();
      const alert = alerts.find((a) => a.name === 'TSDB Write Failures');
      expect(alert).toBeDefined();

      const condition = alert.conditions[0];
      expect(condition.evaluator.type).toBe('gt');
      expect(condition.evaluator.params[0]).toBe(0);
    });
  });

  describe('Collapsible rows are present for each pipeline stage', () => {
    const expectedRows = [
      'Ingestion',
      'Broker',
      'ML Service',
      'Correction Engine',
      'TSDB Writer',
      'End-to-End',
    ];

    it.each(expectedRows)('row "%s" exists with type "row"', (rowTitle) => {
      const row = dashboard.panels.find(
        (p: any) => p.type === 'row' && p.title === rowTitle
      );
      expect(row).toBeDefined();
      expect(row.type).toBe('row');
    });
  });
});
