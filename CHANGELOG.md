# Changelog

## [0.2.0] - 2024-08-10 — Digital Twin Experience

### Summary

Transforms the platform from a raw sensor data pipeline into a true digital twin experience for turbofan engine prognostics. Adds engine-level health monitoring, Remaining Useful Life (RUL) prediction, degradation trajectory visualization, component health mapping, and a visual engine schematic — all in real time via WebSocket.

### Added

#### Backend Services
- **RUL Predictor** (`prognostics/rul_predictor.py`) — Computes Remaining Useful Life (0–125 cycles) per engine using piecewise-linear degradation model. Emits `urgent_attention` events when RUL drops below 30.
- **Health Index Aggregator** (`prognostics/health_index.py`) — Computes composite health score (0.0–1.0) per engine per cycle using weighted sensor deviations from baseline. Top 3 sensors (HPC temp, core speed, fan speed) carry 55% weight.
- **Degradation Curve Tracker** (`prognostics/degradation_tracker.py`) — Records health index trajectory per engine. Computes degradation rate via linear least-squares over last 20 cycles. Emits accelerated degradation events.
- **Component Health Mapper** (`prognostics/component_health.py`) — Maps 21 sensors to 6 engine subsystems (fan, LPC, HPC, HPT, LPT, combustor). Computes per-subsystem health with classification hysteresis (nominal/degraded/critical).
- **Engine Snapshot API** (`api/engines.py`) — `GET /api/engines/{engine_id}/snapshot` returns full prognostic state for WebSocket reconnection recovery.
- **Application lifecycle wiring** — All services register at startup, subscribe to `corrections.state`, and broadcast results via WebSocket.

#### Frontend Views
- **Fleet Overview** (`/fleet`) — Card grid showing all monitored engines sorted by urgency (RUL ascending). Each card displays unit ID, health gauge, RUL countdown, and classification badge. Color-coded green/amber/red.
- **Engine Dashboard** (`/engine/[id]`) — Prominent RUL indicator with critical emphasis at <30 cycles. Health trajectory line chart (Recharts). Degradation rate display. Engine selector dropdown.
- **Engine Schematic** — SVG turbofan cross-section with 6 color-coded subsystem regions. Tooltip on hover shows health score (2dp) and classification. Accessible with text labels and screen reader support.

#### WebSocket Integration
- Extended `WebSocketBroadcastManager` with message types: `rul_update`, `health_index_update`, `subsystem_health_update`, `degradation_update`
- Frontend Zustand store slice with actions for all digital twin message types
- `useWebSocket` hook routes new message types to store actions
- Snapshot restore on WebSocket reconnection

#### Testing
- 25 property-based tests (Hypothesis/fast-check) covering all design correctness properties
- Unit tests for all 4 backend services + 3 frontend views
- Integration tests for end-to-end pipeline (corrections.state → services → WebSocket → frontend state)
- Total test count: ~800 (backend 683 + frontend 120)

### Changed
- C-MAPSS adapter now streams 3 engines by default (was 1)
- Landing page hero CTA now links to Fleet Overview as primary action
- Health Index formula caps per-sensor deviation at 3 std devs to prevent extreme values with partial baselines

### Fixed
- `configure_engine_services()` wiring was missing from `run_local.py` — snapshot API returned 404 for all engines
- Component Health Mapper expected `value`/`cycle` payload fields that don't exist in EnKF output — fixed to use `corrected_state_vector[0]` and duplicate-sensor cycle detection
- Degradation Curve Tracker was not receiving data — wired as dependency of Health Index Aggregator

---

## [0.1.0] — Initial Pipeline

- Real-time sensor ingestion via WebSocket
- ML ensemble prediction (LSTM + XGBoost)
- Ensemble Kalman Filter state correction
- Anomaly detection with innovation-based thresholds
- REST API with health endpoints
- C-MAPSS replay adapter
- 486 property-based + unit tests
