# Data Sources for Digital Twin Telemetry Engine

This document catalogs all real-world and public data sources evaluated for testing and demonstrating the Digital Twin Telemetry Engine pipeline. Sources are organized by domain and rated for compatibility with our architecture.

## Legend

| Field | Meaning |
|-------|---------|
| **Type** | Live stream, REST polling, or static dataset (replay) |
| **Auth** | None, Free API key, or Paid |
| **Fit** | How well it maps to our TelemetryEvent schema (★★★ = perfect) |
| **Status** | Planned / In Use / Evaluated |

---

## 1. Industrial / Predictive Maintenance

### 1.1 NASA C-MAPSS Turbofan Engine Data ★★★ [RECOMMENDED - IN USE]

| Field | Value |
|-------|-------|
| **Source** | [NASA Open Data](https://data.nasa.gov/dataset/cmapss-jet-engine-simulated-data) |
| **Type** | Static dataset (replay as stream) |
| **Auth** | None |
| **Format** | Space-separated text files, 26 columns |
| **Fit** | ★★★ |
| **Status** | In Use |

**Description:** Run-to-failure multivariate time-series data from simulated commercial turbofan engines. Each engine has 21 sensor channels recorded over successive flight cycles until failure. Four sub-datasets cover different operational conditions and fault modes.

**Sensors (21 channels):**
- Fan inlet temperature, LPC/HPC outlet temperatures
- LPT/HPT outlet temperatures, fan/core speeds
- Static/total pressures at multiple stages
- Bypass ratio, bleed enthalpy, coolant flow
- Physical fan/core speeds, corrected fan speed

**Why it's ideal:**
- Multivariate time-series with physically meaningful degradation patterns
- Perfect for demonstrating ML prediction + EnKF correction on real physics
- Gold standard in predictive maintenance research
- Shows clear progression: normal → degrading → failure

**Integration approach:** Replay adapter reads CSV rows, maps engine_id to sensor_id, each of 21 columns becomes a separate TelemetryEvent stream. Configurable playback speed (1x to 1000x).

---

### 1.2 NASA C-MAPSS Aircraft Engine Simulator (Extended)

| Field | Value |
|-------|-------|
| **Source** | [NASA C-MAPSS](https://data.nasa.gov/dataset/c-mapss-aircraft-engine-simulator-data) |
| **Type** | Static dataset (replay as stream) |
| **Auth** | None |
| **Format** | Text files, flight-level simulation |
| **Fit** | ★★★ |
| **Status** | Planned |

**Description:** Extended C-MAPSS data with full flight profile simulation. Includes ascent from sea level to 35K ft and descent, with faults injected at specific points. More granular than the basic CMAPSS dataset — includes flight condition transitions and per-flight sensor snapshots.

**Integration approach:** Same replay adapter as 1.1, with additional flight-phase metadata.

---

## 2. Aviation / Aerospace

### 2.1 OpenSky Network (Real-Time Flight Tracking)

| Field | Value |
|-------|-------|
| **Source** | [OpenSky Network API](https://openskynetwork.github.io/opensky-api/) |
| **Type** | Live REST API (polling every 5-10s) |
| **Auth** | None for anonymous (rate-limited), free account for higher limits |
| **Format** | JSON (state vectors) |
| **Fit** | ★★☆ |
| **Status** | Planned |

**Description:** Community-powered ADS-B receiver network providing real-time aircraft state vectors worldwide. Data includes position, altitude, velocity, heading, vertical rate, and callsign for thousands of aircraft simultaneously.

**Available telemetry per aircraft:**
- Latitude, longitude, barometric/geometric altitude
- Velocity (ground speed), true track (heading)
- Vertical rate, on_ground status
- Squawk code, SPI flag
- Position source (ADS-B, MLAT, etc.)

**Use case for our engine:** Model a fleet of aircraft as a "digital twin" of airspace. Predict trajectories, detect anomalous flight paths (diversions, unusual descent rates), and correct predictions against live position updates via EnKF.

**Limitations:** Not true sensor data (it's derived ADS-B). Rate-limited to 5-10 second intervals for anonymous access. Better suited for trajectory prediction than equipment health monitoring.

**Integration approach:** Polling adapter fetches `/states/all` every 10s, maps each aircraft ICAO24 address to a sensor_id, and streams position/velocity as telemetry events.

---

## 3. Environmental / Infrastructure

### 3.1 USGS Water Data APIs (Real-Time Streamflow & Water Quality)

| Field | Value |
|-------|-------|
| **Source** | [USGS Water Services](https://waterservices.usgs.gov/) / [Water Data APIs](https://api.waterdata.usgs.gov/) |
| **Type** | Live REST API (readings every 15 minutes, transmitted hourly) |
| **Auth** | None |
| **Format** | JSON, XML, RDB (tab-delimited) |
| **Fit** | ★★★ |
| **Status** | Planned |

**Description:** Real-time sensor data from thousands of USGS monitoring stations across the United States. Measures streamflow, gage height, water temperature, dissolved oxygen, turbidity, conductivity, and hundreds of other parameters. Readings are typically taken every 15 minutes and many are transmitted via telemetry within minutes.

**Available telemetry:**
- Streamflow (cubic feet per second)
- Gage height (feet)
- Water temperature (°C)
- Dissolved oxygen (mg/L)
- Specific conductance (µS/cm)
- Turbidity (NTU)
- pH, precipitation, groundwater levels

**Use case for our engine:** Digital twin of a river system or watershed. Predict flood conditions, detect contamination events (sudden turbidity or conductivity spikes), model dam/reservoir behavior. The EnKF is particularly well-suited here — hydrological models are imperfect and real-time sensor correction is standard practice in this domain.

**Why it's excellent:**
- Truly real-time operational data (not historical replays)
- Multi-sensor per station (temperature, flow, height simultaneously)
- Thousands of stations = massive scale testing
- No authentication required
- Government data = no licensing concerns

**Integration approach:** Polling adapter queries the Instantaneous Values Service for selected sites every 5-15 minutes. Each site + parameter combination maps to a sensor_id.

---

### 3.2 Open-Meteo Weather API (Real-Time Weather)

| Field | Value |
|-------|-------|
| **Source** | [Open-Meteo](https://open-meteo.com/) |
| **Type** | Live REST API (updates every 15 min) |
| **Auth** | None (completely free, no key) |
| **Format** | JSON |
| **Fit** | ★★☆ |
| **Status** | Planned |

**Description:** Free weather forecast and historical weather API. Provides current conditions, hourly forecasts, and historical data from 1940 onward. Covers 30+ weather models globally.

**Available telemetry:**
- Temperature, humidity, pressure
- Wind speed/direction/gusts
- Solar radiation, UV index
- Precipitation, cloud cover
- Soil temperature and moisture (multiple depths)

**Use case for our engine:** Digital twin of a building HVAC system, solar farm, or agricultural environment. Predict energy demand based on weather trends, detect anomalous weather conditions affecting operations.

**Integration approach:** Polling adapter fetches current conditions for configured locations. Each location + parameter = sensor_id.

---

### 3.3 OpenWeatherMap (Real-Time Weather)

| Field | Value |
|-------|-------|
| **Source** | [OpenWeatherMap](https://openweathermap.org/) |
| **Type** | Live REST API |
| **Auth** | Free API key (1,000 calls/day free tier) |
| **Format** | JSON, XML |
| **Fit** | ★★☆ |
| **Status** | Evaluated |

**Description:** Global weather data for 200,000+ cities. Current conditions, hourly/daily forecasts, and historical data. More established than Open-Meteo but requires a free API key.

**Integration approach:** Same as Open-Meteo. Slightly more limited on free tier due to daily call cap.

---

## 4. System / Behavioral Telemetry

### 4.1 Airship Real-Time Data Streaming (User/App Behavioral Telemetry)

| Field | Value |
|-------|-------|
| **Source** | [Airship RTDS API](https://www.airship.com/docs/developer/rest-api/connect/) |
| **Type** | Live streaming (newline-delimited JSON, persistent connection) |
| **Auth** | Airship account required (paid platform, free trial available) |
| **Format** | Newline JSON stream |
| **Fit** | ★★☆ |
| **Status** | Planned |

**Description:** Airship's Real-Time Data Streaming (RTDS) delivers user-level events as they happen via a persistent streaming connection. Events include push notification deliveries, app opens, user interactions, custom events, and system-driven events (location, beacon encounters).

**Available telemetry:**
- Push notification sent/delivered/opened events
- App open/close/foreground/background events
- Custom events (purchases, button clicks, screen views)
- Location events (geofence enter/exit, beacon proximity)
- Uninstall/reinstall events
- Consent/opt-in compliance events

**Use case for our engine:** Digital twin of user engagement or app health. Predict user churn patterns, detect anomalous drop-offs in engagement (is a notification system failing?), model behavioral patterns across time. The ML ensemble can predict expected engagement rates and the EnKF can correct against actual incoming events.

**Unique value:** This demonstrates the engine working on non-physical telemetry — proving it's not limited to industrial IoT but generalizes to any time-series prediction/correction problem.

**Integration approach:** Connect to Airship's `/api/events/` streaming endpoint. Map event types to measurement_types, device/user IDs to sensor_ids, and aggregate metrics (events/minute, open rates) as the numeric values.

---

## 5. IoT Platforms / General Telemetry

### 5.1 ThingsBoard (Open-Source IoT Platform)

| Field | Value |
|-------|-------|
| **Source** | [ThingsBoard](https://thingsboard.io/) |
| **Type** | Self-hosted platform with REST/WebSocket/MQTT APIs |
| **Auth** | Self-hosted (free), or cloud (free tier) |
| **Format** | JSON |
| **Fit** | ★★★ |
| **Status** | Evaluated |

**Description:** Open-source IoT platform that can act as a data source. Supports device telemetry ingestion via MQTT, HTTP, CoAP, and LwM2M. Has built-in device simulators and can proxy real hardware data. Could serve as an intermediary between real IoT devices and our pipeline.

**Integration approach:** Subscribe to ThingsBoard's telemetry WebSocket or use REST API to poll device data.

---

### 5.2 Adafruit IO (Maker IoT Cloud)

| Field | Value |
|-------|-------|
| **Source** | [Adafruit IO](https://io.adafruit.com/) |
| **Type** | REST API + MQTT |
| **Auth** | Free account (30 data points/min free tier) |
| **Format** | JSON |
| **Fit** | ★★☆ |
| **Status** | Evaluated |

**Description:** Cloud service for hobbyist IoT projects. Connect real hardware (ESP32, Raspberry Pi) and stream sensor readings. Public feeds from community users provide free data streams.

**Integration approach:** Subscribe to public feeds or connect real hardware. Each feed maps to a sensor_id.

---

### 5.3 ElthroThings (Student IoT Platform)

| Field | Value |
|-------|-------|
| **Source** | [ElthroThings](https://eltrothings.com/) |
| **Type** | REST API + MQTT |
| **Auth** | Free (designed for students) |
| **Format** | JSON |
| **Fit** | ★★☆ |
| **Status** | Evaluated |

**Description:** Free sandboxed IoT cloud for students and educators. Connect ESP32 or Raspberry Pi hardware, ingest telemetry, and control actuators. Good for demonstrations with real physical sensors on a budget.

---

## 6. Financial / Market Data (Stretch Goal)

### 6.1 Cryptocurrency WebSocket Streams

| Field | Value |
|-------|-------|
| **Source** | Binance, Coinbase, Kraken WebSocket APIs |
| **Type** | Live WebSocket stream |
| **Auth** | None for public market data |
| **Format** | JSON |
| **Fit** | ★☆☆ |
| **Status** | Evaluated |

**Description:** Real-time price ticks, order book updates, and trade streams. Free, no authentication required for public market data. Extremely high frequency (hundreds of events per second).

**Use case:** While not traditional "sensor" data, treating price feeds as telemetry demonstrates the engine's generality. The EnKF can correct price predictions against market microstructure, and anomaly detection flags flash crashes or unusual volume.

**Limitation:** The physics of markets don't follow the same patterns as physical systems. ML prediction accuracy will be lower, but the pipeline mechanics are fully exercised.

---

## Testing Roadmap

Recommended order for testing with real data:

| Phase | Source | Why |
|-------|--------|-----|
| **1 (Now)** | NASA C-MAPSS | Perfect fit, offline replay, validates full pipeline with meaningful physics |
| **2** | USGS Water Data | True real-time, no auth, multi-sensor, validates live streaming adapter |
| **3** | OpenSky Network | High-frequency live data, validates scale and trajectory prediction |
| **4** | Open-Meteo Weather | Simple live source, validates multi-location environmental monitoring |
| **5** | Airship RTDS | Non-physical telemetry, validates generalization to behavioral data |
| **6** | ThingsBoard + real hardware | End-to-end with physical sensors, validates production deployment |

## Architecture Note: Adapter Pattern

Each data source connects via a **Source Adapter** that translates the native format into our standard `TelemetryEvent` schema:

```
┌─────────────┐    ┌──────────────┐    ┌──────────────────────┐
│ Data Source  │───▶│ Source       │───▶│ TelemetryEvent       │
│ (any format) │    │ Adapter      │    │ {timestamp, sensor_id,│
└─────────────┘    │              │    │  measurement_type,    │
                   │ - Polling    │    │  value}               │
                   │ - WebSocket  │    └──────────┬───────────┘
                   │ - File Replay│               │
                   └──────────────┘               ▼
                                        [Existing Pipeline - unchanged]
```

The pipeline itself never changes. Only the adapter is source-specific. This is why we can test against any of these sources — the ingestion server, broker, ML service, EnKF, and API gateway remain identical regardless of where the data originates.
