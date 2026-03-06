# Power Market Simulator

A **FastAPI + Pydantic** service that simulates electricity market dispatch using merit-order clearing and unit-commitment constraints. Originally modelled on the DK1 (Western Denmark) grid.

## What it does

The simulator clears an hourly electricity market by:

1. Sorting generators by marginal cost (merit order)
2. Dispatching cheapest-first until demand is met
3. Resolving operational constraints (ramp rates, minimum stable output, lock times)
4. Recording market clearing prices, per-generator dispatch, and system costs

## Installation

```bash
# Requires Python 3.11+
pip install poetry
poetry install
```

## Running the API

```bash
poetry run uvicorn api.main:app --reload
```

Then open <http://127.0.0.1:8000/docs> for interactive OpenAPI documentation.

## Running tests

```bash
poetry run pytest -v
```

## API overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Liveness probe |
| `/simulate` | POST | Run a market simulation |

### Simulation modes

**Simple mode** – provide a high-level generation mix:

```json
{
  "scenario_name": "Base case",
  "horizon_hours": 48,
  "mode": "simple",
  "demand": { "flat_demand_mw": 2000 },
  "simple_mix": {
    "nuclear_mw": 2000,
    "gas_mw": 1500,
    "hydro_mw": 500
  }
}
```

**Advanced mode** – provide detailed per-generator parameters:

```json
{
  "scenario_name": "Custom generators",
  "horizon_hours": 24,
  "mode": "advanced",
  "demand": { "flat_demand_mw": 1500 },
  "generators": [
    {
      "technology": "nuclear",
      "p_max": 1000,
      "p_min": 500,
      "marginal_cost": 5,
      "lock_time": 24
    },
    {
      "technology": "gas",
      "p_max": 800,
      "p_min": 0,
      "marginal_cost": 40
    }
  ]
}
```

### Example response (abbreviated)

```json
{
  "scenario_name": "Base case",
  "horizon_hours": 48,
  "mode": "simple",
  "intervals": [0, 1, 2, "..."],
  "price_series": [5.0, 5.0, "..."],
  "demand_series": [2000.0, 2000.0, "..."],
  "generator_series": [
    {
      "generator_id": 0,
      "generator_name": "nuclear_0",
      "technology": "nuclear",
      "dispatched_mw": [1000.0, 1000.0, "..."],
      "curtailed_mw": [0.0, 0.0, "..."],
      "is_online": [true, true, "..."]
    }
  ],
  "technology_aggregates": [
    {
      "technology": "nuclear",
      "total_dispatched_mwh": 48000.0,
      "capacity_factor": 1.0,
      "installed_capacity_mw": 2000.0
    }
  ],
  "summary": {
    "total_generation_mwh": 96000.0,
    "total_demand_mwh": 96000.0,
    "average_price": 5.0,
    "max_price": 5.0,
    "min_price": 5.0,
    "total_energy_cost": 480000.0,
    "total_startup_cost": 0.0,
    "total_shutdown_cost": 0.0,
    "total_system_cost": 480000.0
  },
  "config_used": { "generators": ["..."] },
  "warnings": []
}
```

## Project structure

```
src/
  power_market_simulator/       # Core simulation engine (no HTTP dependencies)
    engine/
      market.py                 # Market class – merit-order dispatch + constraints
      setup.py                  # Load schedule & generator bid setup
      solar.py                  # Solar power producer (cosine² curve)
      weather.py                # Stochastic weather factor generation
    service.py                  # Service layer: Pydantic models ↔ engine DataFrames
  api/
    main.py                     # FastAPI app
    models.py                   # Pydantic request/response schemas
tests/
  test_engine.py                # Core simulation unit tests
  test_models.py                # Schema validation tests
  test_api.py                   # API integration tests
data/
  DK1_load.csv                  # Historical DK1 load data (ENTSO-E Transparency 2015-2020)
```

## Legacy files

The original script-based entrypoint (`main.py`) and Plotly chart module
(`chart.py`) remain in the repository root for reference. They are **not**
required by the API.

## Data

Load data comes from ENTSO-E Transparency for the DK1 (Western Denmark) region
(2015–2020). The API does **not** require this file — demand can be specified
directly in the request.
