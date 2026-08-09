import React from 'react';
import { render, screen, cleanup } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import LandingPage from '../page';

// Mock next/link to render a plain anchor
vi.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...props }: any) =>
    React.createElement('a', { href, ...props }, children),
}));

// Mock framer-motion to render plain divs
vi.mock('framer-motion', () => ({
  motion: {
    div: React.forwardRef(({ children, variants, initial, animate, whileInView, whileHover, viewport, transition, ...props }: any, ref: any) =>
      React.createElement('div', { ...props, ref }, children)),
    h1: React.forwardRef(({ children, variants, initial, animate, ...props }: any, ref: any) =>
      React.createElement('h1', { ...props, ref }, children)),
    p: React.forwardRef(({ children, variants, initial, animate, ...props }: any, ref: any) =>
      React.createElement('p', { ...props, ref }, children)),
  },
  AnimatePresence: ({ children }: any) => React.createElement(React.Fragment, null, children),
}));

describe('Landing Page', () => {
  afterEach(() => cleanup());

  describe('Required sections render', () => {
    beforeEach(() => {
      render(<LandingPage />);
    });

    it('renders the hero section with tagline', () => {
      expect(
        screen.getByText(/predictive intelligence/i)
      ).toBeInTheDocument();
    });

    it('renders the Architecture section with flow steps', () => {
      expect(screen.getByText('How it works')).toBeInTheDocument();
      expect(screen.getByText('Sensors')).toBeInTheDocument();
      expect(screen.getByText('Ingestion')).toBeInTheDocument();
      expect(screen.getByText('ML Prediction')).toBeInTheDocument();
      expect(screen.getByText('EnKF Correction')).toBeInTheDocument();
      expect(screen.getByText('API')).toBeInTheDocument();
    });

    it('renders the Data Sources section', () => {
      expect(screen.getByText('11 Data Sources')).toBeInTheDocument();
      expect(screen.getByText('NASA C-MAPSS')).toBeInTheDocument();
      expect(screen.getByText('USGS Water')).toBeInTheDocument();
      expect(screen.getByText('OpenSky Network')).toBeInTheDocument();
    });

    it('renders the Roadmap section', () => {
      expect(screen.getByRole('heading', { name: 'Roadmap' })).toBeInTheDocument();
      expect(screen.getByText('Backend pipeline')).toBeInTheDocument();
      expect(screen.getByText('React dashboard')).toBeInTheDocument();
    });

    it('renders the Tech Stack section', () => {
      expect(screen.getByText('Tech Stack')).toBeInTheDocument();
      expect(screen.getByText('Python')).toBeInTheDocument();
      expect(screen.getByText('FastAPI')).toBeInTheDocument();
      expect(screen.getByText('Next.js 14')).toBeInTheDocument();
      expect(screen.getByText('TailwindCSS')).toBeInTheDocument();
    });

    it('renders the CTA button "View Live Dashboard"', () => {
      expect(screen.getByText('View Live Dashboard')).toBeInTheDocument();
    });

    it('renders a GitHub link', () => {
      // The page has "Source Code" button and GitHub links
      const githubLinks = screen.getAllByRole('link').filter(
        (link) => link.getAttribute('href')?.includes('github.com')
      );
      expect(githubLinks.length).toBeGreaterThan(0);
    });
  });

  describe('CTA button links to /dashboard', () => {
    it('has href pointing to /dashboard', () => {
      render(<LandingPage />);

      const ctaLink = screen.getByText('View Live Dashboard').closest('a');
      expect(ctaLink).toHaveAttribute('href', '/dashboard');
    });
  });

  describe('Design system compliance', () => {
    it('uses dark-first design system structure', () => {
      const { container } = render(<LandingPage />);

      // Root div has min-h-screen and bg-background
      const root = container.firstElementChild;
      expect(root).not.toBeNull();
      expect(root!.className).toContain('min-h-screen');
      expect(root!.className).toContain('bg-background');
    });

    it('has a navigation bar', () => {
      render(<LandingPage />);

      const nav = screen.getByRole('navigation');
      expect(nav).toBeInTheDocument();
    });
  });
});


// --- Dashboard skeleton placeholder tests ---

import { useStore } from '@/store';
import DashboardPage from '../dashboard/page';
import { cleanup as rtlCleanup } from '@testing-library/react';

// Mock useWebSocket so it doesn't try to open a real connection
vi.mock('@/hooks/useWebSocket', () => ({
  useWebSocket: vi.fn(),
  default: vi.fn(),
}));

// Mock recharts since jsdom doesn't support SVG rendering
vi.mock('recharts', () => {
  const React = require('react');
  return {
    ResponsiveContainer: ({ children }: any) =>
      React.createElement('div', { 'data-testid': 'responsive-container' }, children),
    LineChart: ({ children }: any) =>
      React.createElement('div', { 'data-testid': 'line-chart' }, children),
    Line: (props: any) =>
      React.createElement('div', { 'data-testid': `line-${props.dataKey}` }),
    XAxis: () => React.createElement('div', { 'data-testid': 'x-axis' }),
    YAxis: () => React.createElement('div', { 'data-testid': 'y-axis' }),
    CartesianGrid: () => React.createElement('div', { 'data-testid': 'cartesian-grid' }),
    Tooltip: () => React.createElement('div', { 'data-testid': 'tooltip' }),
    Legend: () => React.createElement('div', { 'data-testid': 'legend' }),
  };
});

// Mock @radix-ui/react-select to avoid portal issues in jsdom
vi.mock('@radix-ui/react-select', () => {
  const React = require('react');
  return {
    Root: ({ children }: any) => React.createElement('div', null, children),
    Trigger: ({ children }: any) =>
      React.createElement('button', { 'data-testid': 'select-trigger' }, children),
    Value: ({ placeholder }: any) =>
      React.createElement('span', null, placeholder ?? ''),
    Portal: ({ children }: any) => React.createElement('div', null, children),
    Content: ({ children }: any) => React.createElement('div', null, children),
    Viewport: ({ children }: any) => React.createElement('div', null, children),
    Item: ({ children }: any) => React.createElement('div', null, children),
    ItemText: ({ children }: any) => React.createElement('span', null, children),
    ItemIndicator: ({ children }: any) => React.createElement('span', null, children),
    Icon: ({ children }: any) => React.createElement('span', null, children),
    Group: ({ children }: any) => React.createElement('div', null, children),
    Label: ({ children }: any) => React.createElement('label', null, children),
    Separator: () => React.createElement('hr'),
    ScrollUpButton: ({ children }: any) => React.createElement('div', null, children),
    ScrollDownButton: ({ children }: any) => React.createElement('div', null, children),
  };
});

function resetStore() {
  useStore.setState({
    sensorData: {},
    anomalies: [],
    sensorHealth: {},
    pipelineHealth: null,
    connection: {
      status: 'disconnected',
      reconnectAttempts: 0,
      lastConnected: null,
      nextRetryMs: null,
    },
    activeSource: 'nasa-cmapss',
    ui: { isLoading: false, error: null, isSwitchingSource: false },
  });
}

describe('Dashboard Page - Skeleton Placeholders', () => {
  beforeEach(resetStore);
  afterEach(() => rtlCleanup());

  it('shows skeleton panels when sensorData is empty', () => {
    const { container } = render(<DashboardPage />);

    const skeletonElements = container.querySelectorAll('.animate-pulse');
    expect(skeletonElements.length).toBeGreaterThan(0);
  });

  it('shows skeleton panels for sensor health when no sensors connected', () => {
    const { container } = render(<DashboardPage />);

    const sensorHealthSection = screen.getByLabelText('Sensor Health');
    const skeletons = sensorHealthSection.querySelectorAll('.animate-pulse');
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it('does not show sensor chart skeletons when data is available', () => {
    useStore.setState({
      sensorData: {
        'sensor-1': [{ timestamp: 1000, raw: 10, predicted: 11, corrected: 10.5 }],
      },
    });

    render(<DashboardPage />);

    const chartsSection = screen.getByLabelText('Sensor Charts');
    const skeletons = chartsSection.querySelectorAll('.animate-pulse');
    expect(skeletons.length).toBe(0);
  });
});
