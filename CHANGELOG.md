# Changelog

## [0.4.0] - 2026-08-15 — Mission Control (v1.4)

### Summary

Transforms the dashboard into a premium aerospace command center with glassmorphism styling, bento grid layout, and four new backend intelligence modules. Adds anomaly root cause analysis, predictive maintenance alerting, live accuracy benchmarking, and end-to-end latency/throughput monitoring. Frontend delivers a full visual overhaul: interactive SVG turbofan schematic with health-based glow effects, 21-channel telemetry waterfall heatmap, root cause analysis panels, predictive alert notifications, and animated data arrival effects. Also resolves three v1.3 carryover issues (baseline calibration, parallel streaming, insufficient-data UX).

### Added

#### Backend — Intelligence Modules
- **Root Cause Analyzer** (`alerting/root_cause.py`) — Ranks contributing sensors by innovation magnitude (sigma deviation) when anomalies are detected. Rolling 200-cycle history per sensor for statistical context.
- **Predictive Alert System** (`alerting/predictive_alerts.py`) — Uses MonteCarloProjector to forward-project 100 cycles, estimate time-to-critical, and generate severity-classified maintenance recommendations (low/medium/critical).
- **Live Benchmark Runner** (`benchmarking/benchmark_runner.py`) — Continuously computes RMSE, MAE, correction gain %, and confidence coverage against C-MAPSS ground truth over a rolling 5000-sample window.
- **Latency Profiler** (`benchmarking/latency_profiler.py`) — Tracks ingestion-to-correction latency with p50/p95/p99 percentiles. Orphan span eviction after 30s timeout.
- **Throughput Monitor** (`benchmarking/throughput_monitor.py`) — Rolling 10-second window rates for events/sec, predictions/sec, corrections/sec.

#### Backend — REST API Endpoints
- `GET /engines/{id}/anomaly-analysis` — Ranked sensor contributions for latest anomaly
- `GET /engines/{id}/maintenance-recommendations` — Predictive maintenance alerts with time-to-critical
- `GET /metrics/benchmark` — Live accuracy metrics (RMSE, MAE, correction gain, coverage)
- `GET /metrics/performance` — Latency percentiles + throughput rates

#### Frontend — Mission Control Visual Overhaul
- **GlassStatusBar** — Glassmorphism header with PulseIndicator, AnimatedCounter, mini sparklines (polls /metrics/performance every 5s)
- **BentoGrid** — CSS Grid layout with variable card sizes (1x1, 2x1, 1x2, 2x2, 3x2), responsive collapse below 768px
- **GlowCard** — Animated border glow on WebSocket data arrival (cyan/violet/emerald), false→true pulse detection
- **PulseIndicator** — Connection status (green pulse/red static/amber blink) with ARIA labels
- **GradientBorder** — Rotating gradient border with prefers-reduced-motion support
- **AnimatedCounter** — Spring-physics number interpolation via framer-motion
- **TurbofanSchematic** — Interactive SVG cross-section with 7 subsystem regions, CSS glow filters (healthy/warning/critical), animated airflow paths, click-to-expand detail panels, full keyboard accessibility. NO WebGL.
- **TelemetryWaterfall** — Canvas-based 21×50 scrolling heatmap with ring buffer, requestAnimationFrame 60fps rendering, HTML table fallback
- **RootCausePanel** — Horizontal bar charts showing sensor contributions ranked by sigma deviation, loading skeleton, error state with retry
- **PredictiveAlertNotification** — Toast notifications (fixed bottom-right), color-coded by severity, auto-dismiss (low=10s, medium=30s, critical=persists), max 5 visible, stacked by priority
- **EnhancedLineChart** — Recharts wrapper with gradient fills, latest-point glow dot, glass-styled custom tooltip, 200-point performance cap

#### Frontend — Design System
- Mission Control color palette: bg (#0a0b0f), surface-1 (#12141a), surface-2 (#1a1d27), cyan (#00d4ff), violet (#7c3aed), emerald (#10b981), crimson (#ef4444)
- Glow utilities (`.glow-cyan`, `.glow-violet`, `.glow-emerald`), glassmorphism (`.glass`), grid-pattern background
- Hover depth micro-animation (translateY -2px on hover)
- All animations respect `prefers-reduced-motion`

#### Testing
- 6 Hypothesis property tests (sigma deviation, severity classification, correction gain, monotonic percentiles, rate computation, constant history)
- 4 fast-check property tests (BentoGrid item integrity, waterfall buffer bound, GlowCard active toggle, auto-dismiss timing)
- ~100 new frontend unit tests across all v1.4 components
- ~50 new backend unit tests for intelligence modules and API endpoints

### Fixed (v1.3 Carryover)
- **Health Index baseline calibration** — Reports HI=1.0 during first 10 cycles instead of garbage values from unstable baselines. DegradationTracker only receives data from cycle 11+.
- **Parallel engine streaming** — C-MAPSS adapter now interleaves engines round-robin (E1C1, E2C1, E3C1, E1C2...) so all engines start receiving data simultaneously.
- **Insufficient-data UX** — WhatIfStressSlider shows calm progress indicator ("Collecting data: N/20 cycles") instead of red error. Slider disabled during calibration, auto-enables when ready.
- **v1.3 visual polish** — All simulation components wrapped in GlowCard, hardcoded hex replaced with Mission Control tokens, BentoGrid layout on engine detail page.

### Changed
- Default adapter speed reduced to 0.5x (was 10.0x) for realistic observation pace
- Dashboard page (`/dashboard`) rewritten with BentoGrid + GlassStatusBar + grid-pattern background
- Engine detail page uses BentoGrid for simulation components with correct spans
- `run_local.py` wires all v1.4 modules with broker subscriptions for pipeline hooks
- GlowCard extended with "red" and "amber" glow colors for RUL urgency states

---

## [0.3.0] - 2026-08-12 — Interactive Intelligence (v1.3)

### Summary

Adds fault injection and what-if Monte Carlo simulation capabilities to the Digital Twin Engine. Users can now inject artificial sensor faults to demonstrate EnKF resilience in real-time, and run forward projections to explore how operational stress affects remaining useful life. Backend adds a simulation module with FaultInjector, MonteCarloProjector, WhatIfSimulator, and FailureProbabilityCache. Frontend adds 5 new visualization components integrated into the engine detail page.

### Added

#### Backend — Simulation Module (`simulation/`)
- **FaultInjector** (`simulation/fault_injector.py`) — Injects artificial sensor faults (spike, drift, dropout, noise) as a transform layer between raw sensor data and the ingestion pipeline. Supports additive composition, auto-expiry, and per-sensor fast-path lookup.
- **MonteCarloProjector** (`simulation/monte_carlo_projector.py`) — Projects engine health forward using pure NumPy sampling from degradation parameters. 1000 trajectories × 50 cycles in <50ms. Computes percentiles, failure probability curves, expected RUL, and 90% confidence intervals.
- **WhatIfSimulator** (`simulation/what_if_simulator.py`) — Wraps MonteCarloProjector with named scenarios (normal, high_stress, low_stress, maintenance_reset) for user-friendly API access.
- **FailureProbabilityCache** (`simulation/failure_prob_cache.py`) — Background task recomputing failure probability every 30 seconds for all active engines. Serves cached results instantly via GET endpoint.

#### Backend — REST API Endpoints
- **Fault Injection API** (`api/fault_injection_api.py`):
  - `POST /sensors/inject-fault` — Inject a fault (201 with injection_id)
  - `DELETE /sensors/inject-fault` — Clear all faults (200)
  - `GET /sensors/active-faults` — List active faults (200)
- **Simulation API** (`api/simulation_api.py`):
  - `POST /simulation/what-if` — Run stress simulation (200 with percentiles, RUL, CI)
  - `POST /simulation/maintenance-impact` — Simulate maintenance intervention (200)
  - `GET /engines/{id}/failure-probability` — Cached failure probability (200/404)

#### Frontend — Visualization Components
- **FaultInjectionPanel** — Preset buttons (Spike HPC Temp +50%, Dropout Sensor, Add Noise), Clear All, active faults list with colored badges. Polls every 2s.
- **WhatIfStressSlider** — Range slider (0.5x–2.0x) with 300ms debounce, loading indicator, human-readable summary. Distributes simulation results to sibling components.
- **MonteCarloFanChart** — Recharts fan chart with 5th-95th, 25th-75th bands and median line. Critical threshold reference line. Tooltip with all percentile values.
- **DegradationCurveProjection** — Historical solid line + future gradient-faded projection with 90% CI shading. "Now" separator and critical threshold.
- **RULCountdown** — Animated countdown (Framer Motion) with ±N cycles 90% CI. Color-coded (red/amber/green) with pulsing animation when critical.

#### Testing
- 125 new backend tests (6 Hypothesis property test suites + unit tests + API tests)
- 55 new frontend tests (5 component test suites + 11 fast-check property tests)
- Total test count: ~940 (backend 859 + frontend 232 — up from ~800)

### Changed
- Engine detail page (`/engine/[id]`) now integrates all 5 v1.3 components with data flow wired through parent state
- C-MAPSS adapter `stream()` method now calls `FaultInjector.apply()` on each sensor reading before yielding
- `run_local.py` wires FaultInjector singleton, MonteCarloProjector, WhatIfSimulator, and FailureProbabilityCache

### Known Issues
- Health Index drops to ~0.3 during first 10 cycles (baseline calibration issue — see `.kiro/v1.4-known-issues.md`)
- Simulation endpoints return 404 until engine accumulates 20 cycles of data (by design, but UX could be friendlier)

---

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
