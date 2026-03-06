"""Power Market Simulator – FastAPI application.

Start with::

    uvicorn api.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from api.models import SimulationRequest, SimulationResponse
from power_market_simulator.service import run_simulation

app = FastAPI(
    title="Power Market Simulator",
    description=(
        "Electricity market simulation API with merit-order dispatch "
        "and unit-commitment constraints.  Accepts scenario definitions "
        "and returns structured time-series outputs per generator."
    ),
    version="0.1.0",
)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness / readiness probe."""
    return {"status": "ok"}


@app.post(
    "/simulate",
    response_model=SimulationResponse,
    tags=["simulation"],
    summary="Run a market simulation",
)
def simulate(request: SimulationRequest) -> SimulationResponse:
    """Execute a merit-order market simulation.

    Supports two modes:

    * **simple** – provide a high-level generation mix via ``simple_mix``
      and the API fills in operational defaults.
    * **advanced** – provide detailed per-generator parameters via
      ``generators``.

    Returns structured time-series data per generator, technology
    aggregates, and summary metrics.
    """
    try:
        return run_simulation(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
