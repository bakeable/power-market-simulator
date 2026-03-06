# Refactor Plan: Power Market Simulator → FastAPI Service

## Current State

The repository contains a Python-based electricity market simulator modelling
merit-order dispatch and unit-commitment constraints for the DK1 (Western Denmark)
grid region, using real load data from ENTSO-E Transparency (2015-2020).

### Modules

| File | Role | Browser/UI? |
|------|------|-------------|
| `main.py` | Script entrypoint: sets up generators, runs market, shows chart | Yes (calls chart) |
| `market.py` | Core simulation engine: merit-order dispatch, constraint resolution, logging | No |
| `setup.py` | Configuration: loads CSV, defines Generator class, produces bids DataFrame | No |
| `solar.py` | Solar power producer: cosine² generation curve | No |
| `weather.py` | Stochastic weather factor generation (Gaussian-smoothed random) | No |
| `chart.py` | Plotly visualisation (browser popup) | Yes |
| `standard.py` | Shared imports (pandas, numpy) + global config | No |

### Simulation Flow

1. `Setup()` loads DK1 load CSV → `load_schedule` DataFrame
2. Generator units are defined via `Setup.units()` → bid DataFrames
3. `Setup.setup_generator_bids()` consolidates all units
4. `Market(bids, load_schedule)` runs hour-by-hour dispatch:
   - Merit-order sort by marginal cost
   - Constraint detection (online/offline, ramp limits, lock times)
   - Resolution protocol: shutdown non-preferred → curtailment → shutdown marginal
   - Market clearing price = max marginal cost of dispatched units
5. Results stored in `Market.logs` DataFrame
6. `chart(logs)` opens Plotly figure in browser

### Key Findings

- Simulation core (market.py) is already cleanly separated from UI (chart.py)
- No web framework present; chart.py opens local browser
- No packaging (no pyproject.toml, no proper imports)
- No tests
- Type hints are minimal
- Uses `from standard import *` wildcard imports everywhere

## Refactor Plan

### 1. Poetry Setup

- Create `pyproject.toml` with runtime deps (pandas, numpy, scipy, fastapi, uvicorn, pydantic)
- Dev/test deps: pytest, httpx, ruff
- Remove need for `standard.py` wildcard imports

### 2. Package Structure

```
src/
  power_market_simulator/
    __init__.py
    engine/
      __init__.py
      market.py       # Market class (existing logic preserved)
      setup.py         # Setup/Generator (existing logic preserved)
      solar.py         # Solar power producer
      weather.py       # Weather factor generation
    service.py         # Service layer: bridges Pydantic models ↔ engine DataFrames
  api/
    __init__.py
    main.py            # FastAPI app, health endpoint
    models.py          # Pydantic request/response schemas
    routes.py          # /simulate endpoint
tests/
  test_engine.py       # Unit tests for core simulation
  test_models.py       # Schema validation tests
  test_api.py          # API integration tests
data/
  DK1_load.csv         # Renamed load data
```

### 3. Engine Refactoring (minimal)

- Replace `from standard import *` with explicit `import pandas as pd; import numpy as np`
- Make CSV path configurable (not hardcoded)
- Add type hints to public methods
- Keep all domain logic unchanged

### 4. FastAPI API Layer

- `GET /health` → health check
- `POST /simulate` → accepts scenario config, returns structured time series
- Simple mode: user provides MW per technology type, API fills defaults
- Advanced mode: user provides detailed per-generator parameters
- OpenAPI docs auto-generated

### 5. Pydantic Models

- `SimulationRequest`: scenario_name, horizon, demand, generators, mode
- `SimulationResponse`: metadata, intervals, price_series, demand_series, generator_series, technology_aggregates, summary_metrics
- Full validation, defaults, descriptions, examples

### 6. Tests

- Engine: deterministic smoke tests with small scenarios
- Models: schema validation for simple/advanced modes
- API: endpoint tests via TestClient
