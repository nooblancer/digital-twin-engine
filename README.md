# Digital Twin Engine

A real-time digital twin platform that ingests sensor telemetry, predicts future states using ML (LSTM + XGBoost ensemble), and corrects predictions against live observations using an Ensemble Kalman Filter (EnKF).

## Architecture

```
Sensors/Data Source → Ingestion Server → Message Broker → ML Service → Correction Engine → API Gateway
                                              ↓
                                      Time-Series DB
```

## Features

- **High-frequency WebSocket ingestion** — 10,000+ concurrent connections
- **Pluggable data sources** — Switch between 11 real-world datasets from the frontend
- **ML ensemble prediction** — LSTM (temporal) + XGBoost (statistical features)
- **Ensemble Kalman Filter** — Real-time state correction with anomaly detection
- **REST API** — Query current state, history, predictions, and system health
- **486 tests** — Property-based testing with Hypothesis, full integration suite

## Supported Data Sources

| # | Source | Domain | Type |
|---|--------|--------|------|
| 1 | NASA C-MAPSS Turbofan | Industrial | Static replay |
| 2 | USGS Water Data | Environmental | Live API |
| 3 | OpenSky Network | Aviation | Live API |
| 4 | Open-Meteo Weather | Weather | Live API |
| 5 | OpenWeatherMap | Weather | Live API |
| 6 | Airship RTDS | Behavioral | Live stream |
| 7 | ThingsBoard | IoT | Self-hosted |
| 8 | Adafruit IO | IoT/Maker | REST/MQTT |
| 9 | ElthroThings | IoT/Education | REST/MQTT |
| 10 | Crypto WebSocket | Financial | Live stream |
| 11 | NASA C-MAPSS Extended | Industrial | Static replay |

## Quick Start

```bash
# 1. Install backend dependencies
cd backend
pip install -e ".[dev]"

# 2. Download NASA C-MAPSS dataset
cd ../data
python download_cmapss.py

# 3. Run the demo (processes real turbofan engine data)
cd ../backend
python run_cmapss_demo.py --engines 1,2,3 --speed 100

# 4. Run tests
python -m pytest tests/ -q
```

## Project Structure

```
digital-twin-engine/
├── backend/                 Python pipeline services
│   ├── src/
│   │   └── digital_twin_engine/
│   │       ├── ingestion/   WebSocket server
│   │       ├── broker/      Kafka/Redis abstraction
│   │       ├── tsdb/        Time-series DB writer
│   │       ├── ml_service/  LSTM + XGBoost ensemble
│   │       ├── correction/  Ensemble Kalman Filter
│   │       ├── api/         REST API gateway
│   │       ├── simulator/   Synthetic data generator
│   │       ├── adapters/    Data source adapters
│   │       └── shared/      Models, config, logging
│   ├── tests/               486 tests (property-based + unit + integration)
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/                React dashboard (coming soon)
├── data/                    Downloaded datasets
├── docs/                    Data sources catalog, design notes
├── docker-compose.yml       Full pipeline orchestration
└── README.md
```

## Tech Stack

- **Backend:** Python, FastAPI, asyncio, NumPy/SciPy
- **ML:** PyTorch (LSTM), Scikit-Learn (XGBoost)
- **Broker:** Apache Kafka / Redis Pub/Sub
- **Database:** InfluxDB / TimescaleDB
- **Testing:** Hypothesis (property-based), pytest
- **Frontend:** React/Next.js (planned)
- **Deployment:** Docker Compose

## License

MIT
