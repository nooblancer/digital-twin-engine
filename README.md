# Digital Twin Engine

A real-time digital twin platform for turbofan engine prognostics. Ingests NASA C-MAPSS sensor telemetry, predicts future states using ML (LSTM + XGBoost ensemble), corrects predictions against live observations using an Ensemble Kalman Filter (EnKF), and presents the results as an engine-level health monitoring experience with RUL prediction, degradation tracking, and visual component health.

## Architecture

```
C-MAPSS Adapter → Ingestion → ML Service → Correction Engine (EnKF) → Message Broker
                                                                            │
                    ┌───────────────────────────────────────────────────────┘
                    │
                    ├── RUL Predictor ──────────────┐
                    ├── Health Index Aggregator ─────┼── WebSocket → Frontend
                    ├── Component Health Mapper ─────┘
                    └── Degradation Curve Tracker
                                                        │
                                                        ├── Fleet Overview
                                                        ├── Engine Dashboard
                                                        └── Engine Schematic
```

## Features

- **Digital Twin Experience** — Engine-level health monitoring with RUL prediction, degradation curves, and subsystem classification
- **Fleet Overview** — Real-time dashboard showing all engines sorted by urgency with color-coded health cards
- **Engine Schematic** — SVG turbofan cross-section with 6 color-coded subsystem regions and tooltip details
- **RUL Prediction** — Piecewise-linear degradation model producing 0–125 cycle estimates with urgent alerts at <30
- **Component Health Mapping** — 21 sensors mapped to 6 subsystems with hysteresis-based classification (nominal/degraded/critical)
- **High-frequency WebSocket** — Real-time updates to all connected clients
- **ML Ensemble Prediction** — LSTM (temporal) + XGBoost (statistical features)
- **Ensemble Kalman Filter** — Real-time state correction with anomaly detection
- **Pluggable Data Sources** — 11 supported sensor data sources
- **800+ Tests** — Property-based testing with Hypothesis/fast-check, full integration suite

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
- **RUL Indicator** — Prominent countdown with critical emphasis at <30 cycles
- **Health Trajectory** — Line chart showing health index over time (Recharts)
- **Degradation Rate** — Linear fit slope over last 20 cycles
- **Engine Schematic** — SVG subsystem health visualization

## Project Structure

```
digital-twin-engine/
├── backend/
│   ├── src/digital_twin_engine/
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
│   ├── tests/                 683 tests (property + unit + integration)
│   └── run_local.py           Single-process local mode
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── fleet/         Fleet Overview page
│   │   │   └── engine/[id]/   Engine Dashboard page
│   │   ├── components/        EngineSchematic, etc.
│   │   ├── store/             Zustand state (digital-twin slice)
│   │   ├── hooks/             useWebSocket with message routing
│   │   └── types/             TypeScript interfaces
│   └── src/__tests__/         120 tests (unit + property)
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
| `GET /metrics` | Prometheus metrics |
| `WS /ws/telemetry` | Real-time WebSocket stream |

## License

MIT
