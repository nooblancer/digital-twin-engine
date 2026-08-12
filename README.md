# Digital Twin Engine

A real-time digital twin platform for turbofan engine prognostics. Ingests NASA C-MAPSS sensor telemetry, predicts future states using ML (LSTM + XGBoost ensemble), corrects predictions against live observations using an Ensemble Kalman Filter (EnKF), and presents the results as a premium aerospace command center with intelligent alerting, root cause analysis, predictive maintenance, and real-time performance monitoring.

## Architecture

```
C-MAPSS Adapter → FaultInjector → Ingestion → ML Service → Correction Engine (EnKF) → Broker
                                                                                         │
                    ┌────────────────────────────────────────────────────────────────────┘
                    │
                    ├── RUL Predictor ──────────────┐
                    ├── Health Index Aggregator ─────┼── WebSocket → Frontend
                    ├── Component Health Mapper ─────┘
                    ├── Degradation Curve Tracker
                    │         │
                    │         ├── MonteCarloProjector ──→ WhatIfSimulator
                    │         └── FailureProbabilityCache
                    │
                    ├── Root Cause Analyzer ─────────────→ GET /engines/{id}/anomaly-analysis
                    ├── Predictive Alert System ─────────→ GET /engines/{id}/maintenance-recommendations
                    ├── Live Benchmark Runner ───────────→ GET /metrics/benchmark
                    ├── Latency Profiler + Throughput ───→ GET /metrics/performance
                    │
                    └── REST API ──→ Fault Injection / Simulation endpoints
```

## Features

- **Mission Control Dashboard** — Glassmorphism status bar, bento grid layout, glow effects, and grid-pattern background
- **Root Cause Analysis** — Ranks sensors by innovation sigma deviation when anomalies occur
- **Predictive Alerting** — Forward projection to predict time-to-critical with severity classification
- **Live Benchmarking** — Continuous RMSE/MAE metrics against C-MAPSS ground truth
- **Performance Monitoring** — p50/p95/p99 latency percentiles and throughput rates
- **Interactive SVG Schematic** — Turbofan cross-section with health-based glow filters, airflow animations, click-to-expand detail panels
- **Telemetry Waterfall** — 21-channel canvas heatmap scrolling at 60fps
- **Interactive Intelligence** — Inject sensor faults to prove EnKF resilience; run Monte Carlo what-if simulations
- **Fault Injection** — Spike, drift, dropout, noise faults applied in real-time with one-click presets
- **Monte Carlo Simulation** — Forward health projection with confidence fans, failure probability curves, and RUL estimates (<50ms)
- **What-If Stress Slider** — Interactive 0.5x–2.0x stress factor exploration with graceful insufficient-data UX
- **Digital Twin Experience** — Engine-level health monitoring with RUL prediction, degradation curves, and subsystem classification
- **Fleet Overview** — Real-time dashboard showing all engines sorted by urgency with color-coded health cards
- **RUL Prediction** — Piecewise-linear degradation model producing 0–125 cycle estimates with urgent alerts at <30
- **Component Health Mapping** — 21 sensors mapped to 6 subsystems with hysteresis-based classification
- **High-frequency WebSocket** — Real-time updates to all connected clients
- **ML Ensemble Prediction** — LSTM (temporal) + XGBoost (statistical features)
- **Ensemble Kalman Filter** — Real-time state correction with anomaly detection
- **1000+ Tests** — Property-based testing with Hypothesis/fast-check, full integration suite

## Quick Start

```bash
# 1. Install backend dependencies
cd backend
pip install -e ".[dev]"

# 2. Install frontend dependencies
cd ../frontend
npm install

# 3. Run the full platform
cd ../backend
python run_local.py          # Backend on http://localhost:8000

# In another terminal:
cd frontend
npm run dev                  # Frontend on http://localhost:3000

# 4. Open in browser
# Mission Control: http://localhost:3000/dashboard
# Fleet Overview: http://localhost:3000/fleet
# Engine Dashboard: http://localhost:3000/engine/1
```

## Digital Twin Views

### Mission Control Dashboard (`/dashboard`)
The primary monitoring view with a premium dark aerospace aesthetic:
- **GlassStatusBar** — Sticky glassmorphism header with connection pulse, event counter, latency/throughput sparklines
- **BentoGrid** — Dense 4-column grid with variable card sizes (TurbofanSchematic 3×2, TelemetryWaterfall 2×2, charts 2×1, alerts 1×1)
- **TurbofanSchematic** — Interactive SVG with 7 subsystem regions, CSS glow filters by health state, animated airflow, keyboard accessible
- **TelemetryWaterfall** — Canvas-based 21-sensor heatmap scrolling at 60fps
- **RootCausePanel** — Ranked sensor contribution bars when anomalies occur
- **PredictiveAlertNotification** — Toast alerts for predicted critical events

### Fleet Overview (`/fleet`)
Real-time monitoring of all active engine units. Cards sorted by RUL (most urgent first), color-coded by health classification, with live WebSocket updates.

### Engine Dashboard (`/engine/[id]`)
Detailed prognostic view per engine in a BentoGrid layout:
- **RUL Countdown** — Animated countdown with Monte Carlo confidence range (±N cycles, 90% CI)
- **What-If Stress Slider** — Interactive simulation (0.5x–2.0x) with real-time projection updates
- **Monte Carlo Fan Chart** — Forward projection with expanding confidence bands (5th–95th percentile)
- **Degradation Curve & Projection** — Historical line + future gradient projection with CI shading
- **Fault Injection Panel** — One-click presets to inject/clear sensor faults
- **Engine Schematic** — SVG subsystem health visualization
- **EnKF Correction Analysis** — Prediction vs reality with confidence bands

## Project Structure

```
digital-twin-engine/
├── backend/
│   ├── src/digital_twin_engine/
│   │   ├── alerting/           Root cause analysis & predictive alerts
│   │   │   ├── root_cause.py
│   │   │   └── predictive_alerts.py
│   │   ├── benchmarking/       Performance monitoring
│   │   │   ├── benchmark_runner.py
│   │   │   ├── latency_profiler.py
│   │   │   └── throughput_monitor.py
│   │   ├── simulation/         Fault injection & Monte Carlo
│   │   │   ├── fault_injector.py
│   │   │   ├── monte_carlo_projector.py
│   │   │   ├── what_if_simulator.py
│   │   │   └── failure_prob_cache.py
│   │   ├── prognostics/       Digital twin services
│   │   │   ├── rul_predictor.py
│   │   │   ├── health_index.py
│   │   │   ├── degradation_tracker.py
│   │   │   └── component_health.py
│   │   ├── correction/        Ensemble Kalman Filter
│   │   ├── ml_service/        LSTM + XGBoost ensemble
│   │   ├── api/               REST + WebSocket gateway
│   │   ├── broker/            Message transport
│   │   ├── adapters/          Data source adapters
│   │   └── shared/            Models, config, logging
│   ├── tests/                 900+ tests (property + unit + integration)
│   └── run_local.py           Single-process local mode
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── dashboard/     Mission Control dashboard
│   │   │   ├── fleet/         Fleet Overview page
│   │   │   └── engine/[id]/   Engine Dashboard page
│   │   ├── components/
│   │   │   ├── dashboard/     GlassStatusBar, BentoGrid, RootCausePanel, PredictiveAlertNotification
│   │   │   ├── engine/        TurbofanSchematic
│   │   │   ├── visualizations/ EnhancedLineChart, TelemetryWaterfall, MonteCarloFanChart, etc.
│   │   │   └── ui/           GlowCard, PulseIndicator, GradientBorder, AnimatedCounter
│   │   ├── store/             Zustand state (digital-twin + mission-control slices)
│   │   ├── hooks/             useWebSocket with message routing
│   │   ├── lib/               animations.ts utilities
│   │   └── types/             TypeScript interfaces
│   └── src/__tests__/         280+ tests (unit + property)
├── CHANGELOG.md
└── README.md
```

## Tech Stack

- **Backend:** Python 3.14, FastAPI, asyncio, NumPy/SciPy
- **ML:** PyTorch (LSTM), Scikit-Learn (XGBoost)
- **Prognostics:** Piecewise-linear RUL, weighted health index, least-squares degradation
- **Frontend:** Next.js 14, React, TypeScript, Zustand, Recharts, Tailwind CSS
- **Testing:** Hypothesis (Python), fast-check (TypeScript), pytest, Vitest
- **Broker:** In-memory (local mode) / Kafka (production)
- **Deployment:** Docker Compose

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | System health status |
| `GET /api/engines/{id}/snapshot` | Full prognostic state for an engine |
| `GET /api/engines/{id}/anomaly-analysis` | Root cause analysis for latest anomaly |
| `GET /api/engines/{id}/maintenance-recommendations` | Predictive maintenance alerts |
| `GET /api/metrics/benchmark` | Live accuracy metrics (RMSE, MAE, correction gain) |
| `GET /api/metrics/performance` | Latency percentiles + throughput rates |
| `POST /sensors/inject-fault` | Inject a sensor fault (spike/drift/dropout/noise) |
| `DELETE /sensors/inject-fault` | Clear all active faults |
| `GET /sensors/active-faults` | List active fault injections |
| `POST /simulation/what-if` | Run Monte Carlo forward projection |
| `POST /simulation/maintenance-impact` | Simulate maintenance intervention |
| `GET /engines/{id}/failure-probability` | Cached failure probability curve |
| `GET /metrics` | Prometheus metrics |
| `WS /ws/telemetry` | Real-time WebSocket stream |

## License

MIT
