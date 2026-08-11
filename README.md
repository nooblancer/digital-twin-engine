# Digital Twin Engine

A real-time digital twin platform for turbofan engine prognostics. Ingests NASA C-MAPSS sensor telemetry, predicts future states using ML (LSTM + XGBoost ensemble), corrects predictions against live observations using an Ensemble Kalman Filter (EnKF), and presents the results as an interactive engine health monitoring experience with fault injection, Monte Carlo simulation, RUL prediction, and degradation tracking.

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
                    └── REST API ──→ Fault Injection / Simulation endpoints
```

## Features

- **Interactive Intelligence** — Inject sensor faults to prove EnKF resilience; run Monte Carlo what-if simulations to explore future engine behavior
- **Fault Injection** — Spike, drift, dropout, noise faults applied in real-time with one-click presets
- **Monte Carlo Simulation** — Forward health projection with confidence fans, failure probability curves, and RUL estimates (<50ms)
- **What-If Stress Slider** — Interactive 0.5x–2.0x stress factor exploration with debounced API calls
- **Digital Twin Experience** — Engine-level health monitoring with RUL prediction, degradation curves, and subsystem classification
- **Fleet Overview** — Real-time dashboard showing all engines sorted by urgency with color-coded health cards
- **Engine Schematic** — SVG turbofan cross-section with 6 color-coded subsystem regions and tooltip details
- **RUL Prediction** — Piecewise-linear degradation model producing 0–125 cycle estimates with urgent alerts at <30
- **Component Health Mapping** — 21 sensors mapped to 6 subsystems with hysteresis-based classification
- **High-frequency WebSocket** — Real-time updates to all connected clients
- **ML Ensemble Prediction** — LSTM (temporal) + XGBoost (statistical features)
- **Ensemble Kalman Filter** — Real-time state correction with anomaly detection
- **940+ Tests** — Property-based testing with Hypothesis/fast-check, full integration suite

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
# Fleet Overview: http://localhost:3000/fleet
# Engine Dashboard: http://localhost:3000/engine/1
```

## Digital Twin Views

### Fleet Overview (`/fleet`)
Real-time monitoring of all active engine units. Cards sorted by RUL (most urgent first), color-coded by health classification, with live WebSocket updates.

### Engine Dashboard (`/engine/[id]`)
Detailed prognostic view per engine:
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
│   ├── tests/                 859 tests (property + unit + integration)
│   └── run_local.py           Single-process local mode
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── fleet/         Fleet Overview page
│   │   │   └── engine/[id]/   Engine Dashboard page
│   │   ├── components/        Visualizations (FanChart, RULCountdown, etc.)
│   │   ├── store/             Zustand state (digital-twin slice)
│   │   ├── hooks/             useWebSocket with message routing
│   │   └── types/             TypeScript interfaces
│   └── src/__tests__/         232 tests (unit + property)
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
