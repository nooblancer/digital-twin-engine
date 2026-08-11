'use client';

import Link from 'next/link';
import { useState } from 'react';
import { motion } from 'framer-motion';
import { DATA_SOURCES } from '@/lib/data-sources';
import type { DataSource } from '@/types';
import {
  Activity,
  Brain,
  Cpu,
  Database,
  Globe,
  Layers,
  Radio,
  Rocket,
  Server,
  Zap,
  ArrowRight,
  ExternalLink,
  ChevronRight,
} from 'lucide-react';

function GithubIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
    </svg>
  );
}

// ─── Data ────────────────────────────────────────────────────────────────────

const ARCHITECTURE_STEPS = [
  { label: 'Sensors', icon: Radio, description: 'Live telemetry ingestion from 11 data sources' },
  { label: 'Ingestion', icon: Server, description: 'Kafka-backed stream processing pipeline' },
  { label: 'ML Prediction', icon: Brain, description: 'LSTM + XGBoost dual-model forecasting' },
  { label: 'EnKF Correction', icon: Zap, description: 'Ensemble Kalman Filter state correction' },
  { label: 'API', icon: Globe, description: 'REST + WebSocket real-time delivery' },
];

const ROADMAP_ITEMS = [
  { status: 'done', label: 'Backend pipeline', description: 'Core ingestion, prediction, and correction services' },
  { status: 'done', label: 'NASA C-MAPSS adapter', description: 'Turbofan engine degradation simulation' },
  { status: 'done', label: 'Multi-adapter framework', description: '11 data source adapters operational' },
  { status: 'current', label: 'React dashboard', description: 'Real-time visualization frontend' },
  { status: 'upcoming', label: 'Additional adapters', description: 'Community-contributed data sources' },
  { status: 'upcoming', label: 'Production deployment', description: 'Kubernetes orchestration & CI/CD' },
] as const;

const TECH_STACK = [
  { name: 'Python', category: 'Backend' },
  { name: 'FastAPI', category: 'Backend' },
  { name: 'LSTM + XGBoost', category: 'ML' },
  { name: 'EnKF', category: 'ML' },
  { name: 'Kafka', category: 'Infrastructure' },
  { name: 'Prometheus', category: 'Infrastructure' },
  { name: 'Next.js 14', category: 'Frontend' },
  { name: 'TailwindCSS', category: 'Frontend' },
  { name: 'Recharts', category: 'Frontend' },
  { name: 'Zustand', category: 'Frontend' },
];

const DOMAIN_ICONS: Record<string, typeof Activity> = {
  Industrial: Cpu,
  Environmental: Globe,
  Aviation: Rocket,
  IoT: Radio,
  Behavioral: Activity,
  Financial: Layers,
};

const DOMAIN_ORDER = ['Industrial', 'Environmental', 'Aviation', 'IoT', 'Behavioral', 'Financial'] as const;

function groupByDomain(sources: DataSource[]): Record<string, DataSource[]> {
  const grouped: Record<string, DataSource[]> = {};
  for (const source of sources) {
    if (!grouped[source.domain]) grouped[source.domain] = [];
    grouped[source.domain].push(source);
  }
  return grouped;
}

// ─── Animation Variants ──────────────────────────────────────────────────────

const fadeUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
};

const stagger = {
  animate: { transition: { staggerChildren: 0.1 } },
};

// ─── Components ──────────────────────────────────────────────────────────────

function Navbar() {
  return (
    <nav className="fixed top-0 left-0 right-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-md">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2 group">
          <div className="h-8 w-8 rounded-md bg-primary/10 border border-primary/20 flex items-center justify-center group-hover:bg-primary/20 transition-colors">
            <Database className="h-4 w-4 text-primary" />
          </div>
          <span className="font-semibold text-sm text-foreground">Digital Twin Engine</span>
        </Link>

        <div className="hidden sm:flex items-center gap-6">
          <Link href="/fleet" className="text-sm text-muted-foreground hover:text-foreground transition-colors">Fleet</Link>
          <a href="#architecture" className="text-sm text-muted-foreground hover:text-foreground transition-colors">Architecture</a>
          <a href="#sources" className="text-sm text-muted-foreground hover:text-foreground transition-colors">Sources</a>
          <a href="#roadmap" className="text-sm text-muted-foreground hover:text-foreground transition-colors">Roadmap</a>
          <a href="#tech" className="text-sm text-muted-foreground hover:text-foreground transition-colors">Stack</a>
        </div>

        <div className="flex items-center gap-3">
          <a
            href="https://github.com/your-org/digital-twin-engine"
            target="_blank"
            rel="noopener noreferrer"
            className="h-8 w-8 flex items-center justify-center rounded-md hover:bg-accent transition-colors"
            aria-label="GitHub repository"
          >
            <GithubIcon className="h-4 w-4 text-muted-foreground" />
          </a>
          <Link
            href="/dashboard"
            className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            Launch Dashboard
            <ArrowRight className="h-3 w-3" />
          </Link>
        </div>
      </div>
    </nav>
  );
}

function Hero() {
  return (
    <section className="pt-32 pb-16 px-4 sm:px-6">
      <div className="max-w-6xl mx-auto">
        <motion.div
          className="flex flex-col items-center text-center gap-6"
          initial="initial"
          animate="animate"
          variants={stagger}
        >
          <motion.div variants={fadeUp} className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-border/60 bg-card/50 text-xs text-muted-foreground">
            <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
            v1.2 — Real-time pipeline operational
          </motion.div>

          <motion.h1
            variants={fadeUp}
            className="text-4xl sm:text-5xl md:text-6xl font-bold tracking-tight text-foreground max-w-3xl leading-[1.1]"
          >
            Sensor telemetry meets{' '}
            <span className="bg-gradient-to-r from-primary via-[hsl(192,50%,65%)] to-[hsl(150,40%,55%)] bg-clip-text text-transparent">
              predictive intelligence
            </span>
          </motion.h1>

          <motion.p
            variants={fadeUp}
            className="text-base sm:text-lg text-muted-foreground max-w-2xl leading-relaxed"
          >
            Ingest live sensor data, forecast state with dual ML models, and apply Ensemble Kalman Filter
            corrections — all in real time. Monitor anomalies, explore history, and predict failures
            across 11 data domains.
          </motion.p>

          <motion.div variants={fadeUp} className="flex flex-wrap items-center justify-center gap-3 pt-2">
            <Link
              href="/fleet"
              className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-all hover:shadow-lg hover:shadow-primary/20"
            >
              Fleet Overview
              <ArrowRight className="h-4 w-4" />
            </Link>
            <Link
              href="/dashboard"
              className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-medium rounded-md border border-border bg-card hover:bg-accent transition-colors"
            >
              Sensor Dashboard
              <ArrowRight className="h-4 w-4" />
            </Link>
            <a
              href="https://github.com/your-org/digital-twin-engine"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-medium rounded-md border border-border bg-card hover:bg-accent transition-colors"
            >
              <GithubIcon className="h-4 w-4" />
              Source Code
              <ExternalLink className="h-3 w-3 opacity-50" />
            </a>
          </motion.div>
        </motion.div>
      </div>
    </section>
  );
}

function ArchitectureSection() {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  return (
    <section id="architecture" className="py-20 px-4 sm:px-6">
      <div className="max-w-6xl mx-auto">
        <motion.div
          initial="initial"
          whileInView="animate"
          viewport={{ once: true, margin: '-100px' }}
          variants={stagger}
          className="flex flex-col gap-10"
        >
          <motion.div variants={fadeUp} className="flex flex-col gap-2">
            <h2 className="text-2xl font-semibold text-foreground">How it works</h2>
            <p className="text-sm text-muted-foreground max-w-lg">
              Data flows through five stages, from raw sensor readings to corrected, queryable state.
            </p>
          </motion.div>

          <motion.div variants={fadeUp} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
            {ARCHITECTURE_STEPS.map((step, index) => {
              const Icon = step.icon;
              const isHovered = hoveredIndex === index;
              return (
                <motion.div
                  key={step.label}
                  onMouseEnter={() => setHoveredIndex(index)}
                  onMouseLeave={() => setHoveredIndex(null)}
                  className={`group relative flex flex-col gap-3 p-4 rounded-lg border transition-all cursor-default ${
                    isHovered
                      ? 'border-primary/40 bg-primary/5 shadow-md shadow-primary/5'
                      : 'border-border/60 bg-card/50 hover:border-border'
                  }`}
                  whileHover={{ y: -2 }}
                  transition={{ duration: 0.2 }}
                >
                  {/* Step number */}
                  <div className="absolute top-2 right-3 text-[10px] font-mono text-muted-foreground/50">
                    {String(index + 1).padStart(2, '0')}
                  </div>
                  <div className={`h-9 w-9 rounded-md flex items-center justify-center transition-colors ${
                    isHovered ? 'bg-primary/15' : 'bg-muted/50'
                  }`}>
                    <Icon className={`h-4.5 w-4.5 transition-colors ${isHovered ? 'text-primary' : 'text-muted-foreground'}`} />
                  </div>
                  <div>
                    <h3 className="text-sm font-medium text-foreground">{step.label}</h3>
                    <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{step.description}</p>
                  </div>
                  {/* Connector arrow (desktop only) */}
                  {index < ARCHITECTURE_STEPS.length - 1 && (
                    <div className="hidden lg:block absolute -right-2 top-1/2 -translate-y-1/2 z-10">
                      <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/40" />
                    </div>
                  )}
                </motion.div>
              );
            })}
          </motion.div>
        </motion.div>
      </div>
    </section>
  );
}

function DataSourcesSection() {
  const grouped = groupByDomain(DATA_SOURCES);

  return (
    <section id="sources" className="py-20 px-4 sm:px-6 border-t border-border/30">
      <div className="max-w-6xl mx-auto">
        <motion.div
          initial="initial"
          whileInView="animate"
          viewport={{ once: true, margin: '-100px' }}
          variants={stagger}
          className="flex flex-col gap-10"
        >
          <motion.div variants={fadeUp} className="flex flex-col gap-2">
            <h2 className="text-2xl font-semibold text-foreground">11 Data Sources</h2>
            <p className="text-sm text-muted-foreground max-w-lg">
              Plug into industrial sensors, weather APIs, flight trackers, IoT platforms, and financial streams.
            </p>
          </motion.div>

          <motion.div variants={fadeUp} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {DOMAIN_ORDER.map((domain) => {
              const sources = grouped[domain];
              if (!sources || sources.length === 0) return null;
              const Icon = DOMAIN_ICONS[domain] || Activity;
              return (
                <div
                  key={domain}
                  className="group p-4 rounded-lg border border-border/60 bg-card/30 hover:border-primary/30 hover:bg-primary/[0.02] transition-all"
                >
                  <div className="flex items-center gap-2.5 mb-3">
                    <div className="h-7 w-7 rounded-md bg-muted/50 flex items-center justify-center group-hover:bg-primary/10 transition-colors">
                      <Icon className="h-3.5 w-3.5 text-muted-foreground group-hover:text-primary transition-colors" />
                    </div>
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      {domain}
                    </h3>
                  </div>
                  <ul className="flex flex-col gap-1.5">
                    {sources.map((source) => (
                      <li key={source.id} className="text-sm text-foreground/80 flex items-center gap-2">
                        <span className="h-1 w-1 rounded-full bg-muted-foreground/30 flex-shrink-0" />
                        {source.label}
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </motion.div>
        </motion.div>
      </div>
    </section>
  );
}

function RoadmapSection() {
  return (
    <section id="roadmap" className="py-20 px-4 sm:px-6 border-t border-border/30">
      <div className="max-w-6xl mx-auto">
        <motion.div
          initial="initial"
          whileInView="animate"
          viewport={{ once: true, margin: '-100px' }}
          variants={stagger}
          className="flex flex-col gap-10"
        >
          <motion.div variants={fadeUp} className="flex flex-col gap-2">
            <h2 className="text-2xl font-semibold text-foreground">Roadmap</h2>
            <p className="text-sm text-muted-foreground max-w-lg">
              Tracking progress from proof-of-concept to production deployment.
            </p>
          </motion.div>

          <motion.div variants={fadeUp} className="relative">
            {/* Vertical line */}
            <div className="absolute left-[11px] top-2 bottom-2 w-px bg-border/60" />

            <div className="flex flex-col gap-0">
              {ROADMAP_ITEMS.map((item, index) => (
                <div key={item.label} className="relative flex gap-4 py-3 group">
                  {/* Dot */}
                  <div className={`relative z-10 mt-0.5 h-[22px] w-[22px] flex-shrink-0 rounded-full border-2 flex items-center justify-center transition-colors ${
                    item.status === 'done'
                      ? 'border-[hsl(var(--status-healthy))] bg-[hsl(var(--status-healthy))]/10'
                      : item.status === 'current'
                        ? 'border-primary bg-primary/10 shadow-sm shadow-primary/20'
                        : 'border-border bg-card'
                  }`}>
                    {item.status === 'done' && (
                      <svg className="h-3 w-3 text-[hsl(var(--status-healthy))]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                    {item.status === 'current' && (
                      <span className="h-2 w-2 rounded-full bg-primary animate-pulse" />
                    )}
                  </div>

                  {/* Content */}
                  <div className="flex flex-col gap-0.5 pb-1">
                    <span className={`text-sm font-medium ${
                      item.status === 'current' ? 'text-foreground' : item.status === 'done' ? 'text-foreground/70' : 'text-muted-foreground'
                    }`}>
                      {item.label}
                    </span>
                    <span className="text-xs text-muted-foreground/70">{item.description}</span>
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        </motion.div>
      </div>
    </section>
  );
}

function TechStackSection() {
  const categories = ['Backend', 'ML', 'Infrastructure', 'Frontend'];

  return (
    <section id="tech" className="py-20 px-4 sm:px-6 border-t border-border/30">
      <div className="max-w-6xl mx-auto">
        <motion.div
          initial="initial"
          whileInView="animate"
          viewport={{ once: true, margin: '-100px' }}
          variants={stagger}
          className="flex flex-col gap-10"
        >
          <motion.div variants={fadeUp} className="flex flex-col gap-2">
            <h2 className="text-2xl font-semibold text-foreground">Tech Stack</h2>
            <p className="text-sm text-muted-foreground max-w-lg">
              Built on proven, production-ready technologies.
            </p>
          </motion.div>

          <motion.div variants={fadeUp} className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {categories.map((category) => (
              <div key={category} className="flex flex-col gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/60">
                  {category}
                </span>
                <div className="flex flex-col gap-1.5">
                  {TECH_STACK.filter((t) => t.category === category).map((tech) => (
                    <span
                      key={tech.name}
                      className="text-sm text-foreground/80 px-2.5 py-1 rounded-md border border-border/40 bg-card/30 hover:border-border hover:bg-card transition-colors"
                    >
                      {tech.name}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </motion.div>
        </motion.div>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="py-8 px-4 sm:px-6 border-t border-border/30">
      <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Database className="h-3.5 w-3.5" />
          <span>Digital Twin Engine</span>
          <span className="text-muted-foreground/40">·</span>
          <span>Open Source</span>
        </div>
        <div className="flex items-center gap-4">
          <a
            href="https://github.com/your-org/digital-twin-engine"
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1.5"
          >
            <GithubIcon className="h-3.5 w-3.5" />
            GitHub
          </a>
          <Link href="/dashboard" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
            Dashboard
          </Link>
        </div>
      </div>
    </footer>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-background">
      <Navbar />
      <Hero />
      <ArchitectureSection />
      <DataSourcesSection />
      <RoadmapSection />
      <TechStackSection />
      <Footer />
    </div>
  );
}
