"""Service layer – bridges Pydantic models to the simulation engine.

This module is deliberately free of HTTP concerns.  It converts API-level
request objects into the DataFrames the :class:`Market` engine expects,
runs the simulation, and converts the resulting logs into a structured
:class:`SimulationResponse`.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from api.models import (
    DemandProfile,
    GeneratorSpec,
    GeneratorTimeSeries,
    SimpleMix,
    SimulationMode,
    SimulationRequest,
    SimulationResponse,
    SummaryMetrics,
    TechnologyAggregate,
)
from power_market_simulator.engine.market import Market
from power_market_simulator.engine.setup import Setup

# ---------------------------------------------------------------------------
# Default assumptions for simple-mode expansion
# ---------------------------------------------------------------------------

_SIMPLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "nuclear": {
        "p_min_frac": 0.5,
        "mc": 5,
        "sc": 0,
        "ramp_hour": 1000,
        "lock_time": 24,
        "online": True,
        "locked": 0,
        "unit_size": 1000,
    },
    "gas": {
        "p_min_frac": 0.0,
        "mc": 40,
        "sc": 0,
        "ramp_hour": 1000,
        "lock_time": 0,
        "online": False,
        "locked": 0,
        "unit_size": 500,
    },
    "coal": {
        "p_min_frac": 0.3,
        "mc": 25,
        "sc": 0,
        "ramp_hour": 500,
        "lock_time": 8,
        "online": False,
        "locked": 0,
        "unit_size": 500,
    },
    "hydro": {
        "p_min_frac": 0.0,
        "mc": 1,
        "sc": 0,
        "ramp_hour": 1000,
        "lock_time": 0,
        "online": False,
        "locked": 0,
        "unit_size": 500,
    },
    "solar": {
        "p_min_frac": 0.0,
        "mc": 0,
        "sc": 0,
        "ramp_hour": 10000,
        "lock_time": 0,
        "online": False,
        "locked": 0,
        "unit_size": 500,
    },
    "wind": {
        "p_min_frac": 0.0,
        "mc": 0,
        "sc": 0,
        "ramp_hour": 10000,
        "lock_time": 0,
        "online": False,
        "locked": 0,
        "unit_size": 500,
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _expand_simple_mix(mix: SimpleMix) -> list[GeneratorSpec]:
    """Convert a simple generation mix into a list of ``GeneratorSpec``."""
    specs: list[GeneratorSpec] = []
    mapping = {
        "nuclear": mix.nuclear_mw,
        "gas": mix.gas_mw,
        "coal": mix.coal_mw,
        "hydro": mix.hydro_mw,
        "solar": mix.solar_mw,
        "wind": mix.wind_mw,
    }
    for tech, total_mw in mapping.items():
        if total_mw <= 0:
            continue
        defaults = _SIMPLE_DEFAULTS[tech]
        unit_size = defaults["unit_size"]
        n_units = max(1, int(np.ceil(total_mw / unit_size)))
        per_unit_mw = total_mw / n_units
        for i in range(n_units):
            specs.append(
                GeneratorSpec(
                    name=f"{tech}_{i}",
                    technology=tech,  # type: ignore[arg-type]
                    p_max=per_unit_mw,
                    p_min=per_unit_mw * defaults["p_min_frac"],
                    marginal_cost=defaults["mc"],
                    shutdown_cost=defaults["sc"],
                    ramp_rate=defaults["ramp_hour"],
                    lock_time=defaults["lock_time"],
                    online=defaults["online"],
                    locked=defaults["locked"],
                )
            )
    return specs


def _build_demand(demand: DemandProfile, horizon: int) -> list[float]:
    """Return an hourly demand list of length *horizon*."""
    if demand.series is not None:
        series = demand.series
        if len(series) >= horizon:
            return series[:horizon]
        # Tile to fill horizon
        reps = (horizon // len(series)) + 1
        return (series * reps)[:horizon]
    if demand.flat_demand_mw is not None:
        return [demand.flat_demand_mw] * horizon
    # Fallback: constant 2000 MW
    return [2000.0] * horizon


def _generators_to_bids(specs: list[GeneratorSpec]) -> pd.DataFrame:
    """Convert a list of GeneratorSpec to the bids DataFrame the engine needs."""
    setup = Setup.__new__(Setup)
    setup.load_schedule = pd.DataFrame()
    setup.original_bids = pd.DataFrame()

    unit_frames: list[pd.DataFrame] = []
    for spec in specs:
        frame = setup.units(
            n_units=1,
            type=spec.technology.value,
            p_min=spec.p_min,
            p_max=spec.p_max,
            mc=spec.marginal_cost,
            sc=spec.shutdown_cost,
            ramp_hour=spec.ramp_rate,
            lock_time=spec.lock_time,
            online=spec.online,
            locked=spec.locked,
        )
        unit_frames.append(frame)

    bids = pd.concat(unit_frames, ignore_index=True)
    bids["id"] = bids.index
    cols = ["id"] + [c for c in bids.columns if c != "id"]
    return bids[cols].copy()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_simulation(request: SimulationRequest) -> SimulationResponse:
    """Execute a full simulation and return a structured response."""
    warnings: list[str] = []

    # ---- Resolve generators ----
    if request.mode == SimulationMode.advanced:
        if not request.generators:
            raise ValueError("Advanced mode requires at least one generator in 'generators'")
        specs = request.generators
    else:
        mix = request.simple_mix or SimpleMix()
        total_capacity = sum([mix.nuclear_mw, mix.gas_mw, mix.coal_mw, mix.hydro_mw, mix.solar_mw, mix.wind_mw])
        if total_capacity == 0:
            # Provide a sensible default
            mix = SimpleMix(nuclear_mw=2000, gas_mw=1500, hydro_mw=500)
            warnings.append("No generation mix specified – using default mix (nuclear 2000, gas 1500, hydro 500 MW)")
        specs = _expand_simple_mix(mix)

    # ---- Resolve demand ----
    demand = request.demand or DemandProfile()
    demand_list = _build_demand(demand, request.horizon_hours)

    # ---- Build engine inputs ----
    bids = _generators_to_bids(specs)
    load_schedule = Setup.load_schedule_from_list(demand_list)

    # ---- Run simulation ----
    market = Market(bids, load_schedule)
    market.start()

    if market.undersupply:
        warnings.append(
            "Load exceeded available generation capacity during the simulation. "
            "Results are partial."
        )

    # ---- Build response ----
    return _build_response(request, specs, demand_list, market, warnings)


# ---------------------------------------------------------------------------
# Response builder
# ---------------------------------------------------------------------------


def _build_response(
    request: SimulationRequest,
    specs: list[GeneratorSpec],
    demand_list: list[float],
    market: Market,
    warnings: list[str],
) -> SimulationResponse:
    logs = market.logs

    if logs.empty:
        n = request.horizon_hours
        return SimulationResponse(
            scenario_name=request.scenario_name,
            description=request.description,
            horizon_hours=request.horizon_hours,
            mode=request.mode.value,
            intervals=list(range(n)),
            price_series=[0.0] * n,
            demand_series=demand_list,
            generator_series=[],
            technology_aggregates=[],
            summary=SummaryMetrics(
                total_generation_mwh=0,
                total_demand_mwh=sum(demand_list),
                average_price=0,
                max_price=0,
                min_price=0,
                total_energy_cost=0,
                total_startup_cost=0,
                total_shutdown_cost=0,
                total_system_cost=0,
            ),
            config_used=_config_used(specs),
            warnings=warnings + ["Simulation produced no output logs."],
        )

    # Assign a flat interval index
    logs = logs.copy()
    logs["interval"] = (
        logs.groupby(["schedule", "hour"]).ngroup()
    )
    n_intervals = int(logs["interval"].max()) + 1

    # ---- Price & demand series ----
    hourly = (
        logs.groupby("interval", sort=True)
        .agg(mcp=("mcp", "first"), load=("load", "first"))
        .reset_index()
    )
    price_series = hourly["mcp"].tolist()
    demand_series = hourly["load"].tolist()

    # ---- Generator time series ----
    gen_series: list[GeneratorTimeSeries] = []
    for gen_id in sorted(logs["id"].unique()):
        g = logs[logs["id"] == gen_id].sort_values("interval")
        tech = g["type"].iloc[0]
        p_max = g["p_max"].iloc[0]
        dispatched = g["dispatch"].tolist()
        curtailed = [max(0.0, p_max - d) if d > 0 else 0.0 for d in dispatched]
        online_status = g["online"].tolist()

        name = f"{tech}_{gen_id}"
        # Try to use spec name if available
        if gen_id < len(specs) and specs[int(gen_id)].name:
            name = specs[int(gen_id)].name  # type: ignore[assignment]

        gen_series.append(
            GeneratorTimeSeries(
                generator_id=int(gen_id),
                generator_name=name,
                technology=tech,
                dispatched_mw=dispatched,
                curtailed_mw=curtailed,
                is_online=[bool(o) for o in online_status],
            )
        )

    # ---- Technology aggregates ----
    tech_agg: list[TechnologyAggregate] = []
    for tech_name, grp in logs.groupby("type"):
        total_dispatched = grp["dispatch"].sum()
        installed = grp.groupby("id")["p_max"].first().sum()
        possible = installed * n_intervals
        cf = total_dispatched / possible if possible > 0 else 0.0
        tech_agg.append(
            TechnologyAggregate(
                technology=str(tech_name),
                total_dispatched_mwh=round(float(total_dispatched), 2),
                capacity_factor=round(float(cf), 4),
                installed_capacity_mw=round(float(installed), 2),
            )
        )

    # ---- Summary ----
    total_gen = logs.groupby("interval")["dispatch"].sum().sum()
    hourly_costs = logs.drop_duplicates("interval")
    summary = SummaryMetrics(
        total_generation_mwh=round(float(total_gen), 2),
        total_demand_mwh=round(sum(demand_series), 2),
        average_price=round(float(np.mean(price_series)), 2),
        max_price=round(float(np.max(price_series)), 2),
        min_price=round(float(np.min(price_series)), 2),
        total_energy_cost=round(float(hourly_costs["energy_costs"].sum()), 2),
        total_startup_cost=round(float(hourly_costs["startup_costs"].sum()), 2),
        total_shutdown_cost=round(float(hourly_costs["shutdown_costs"].sum()), 2),
        total_system_cost=round(float(hourly_costs["system_cost"].sum()), 2),
    )

    return SimulationResponse(
        scenario_name=request.scenario_name,
        description=request.description,
        horizon_hours=request.horizon_hours,
        mode=request.mode.value,
        intervals=list(range(n_intervals)),
        price_series=price_series,
        demand_series=demand_series,
        generator_series=gen_series,
        technology_aggregates=tech_agg,
        summary=summary,
        config_used=_config_used(specs),
        warnings=warnings,
    )


def _config_used(specs: list[GeneratorSpec]) -> dict[str, Any]:
    return {
        "generators": [s.model_dump() for s in specs],
    }
