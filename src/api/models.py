"""Pydantic request / response schemas for the Power Market Simulator API.

Provides models for both **simple** and **advanced** simulation modes plus
the structured time-series response.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SimulationMode(str, Enum):
    simple = "simple"
    advanced = "advanced"


class TechnologyType(str, Enum):
    nuclear = "nuclear"
    gas = "gas"
    coal = "coal"
    hydro = "hydro"
    solar = "solar"
    wind = "wind"
    imports = "imports"
    battery = "battery"
    other = "other"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class SimpleMix(BaseModel):
    """High-level generation mix – the API expands each technology into
    generators with sensible default operational parameters."""

    nuclear_mw: float = Field(0, ge=0, description="Total nuclear capacity (MW)")
    gas_mw: float = Field(0, ge=0, description="Total gas capacity (MW)")
    coal_mw: float = Field(0, ge=0, description="Total coal capacity (MW)")
    hydro_mw: float = Field(0, ge=0, description="Total hydro capacity (MW)")
    solar_mw: float = Field(0, ge=0, description="Total solar capacity (MW)")
    wind_mw: float = Field(0, ge=0, description="Total wind capacity (MW)")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "nuclear_mw": 2000,
                    "gas_mw": 1500,
                    "hydro_mw": 500,
                }
            ]
        }
    }


class GeneratorSpec(BaseModel):
    """Detailed specification for one generator (advanced mode)."""

    name: str | None = Field(None, description="Optional human-friendly name")
    technology: TechnologyType = Field(..., description="Technology / fuel type")
    p_max: float = Field(..., gt=0, description="Maximum power output (MW)")
    p_min: float = Field(0, ge=0, description="Minimum stable output (MW)")
    marginal_cost: float = Field(..., ge=0, description="Marginal cost (€/MWh)")
    shutdown_cost: float = Field(0, ge=0, description="Shutdown cost (€)")
    ramp_rate: float = Field(
        1000, gt=0, description="Maximum hourly ramp rate (MW/h)"
    )
    lock_time: int = Field(
        0, ge=0, description="Minimum down-time after shutdown (hours)"
    )
    online: bool = Field(False, description="Is the unit online at start?")
    locked: int = Field(0, ge=0, description="Hours locked out at start")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "technology": "nuclear",
                    "p_max": 1000,
                    "p_min": 500,
                    "marginal_cost": 5,
                    "shutdown_cost": 0,
                    "ramp_rate": 1000,
                    "lock_time": 24,
                }
            ]
        }
    }


class DemandProfile(BaseModel):
    """Demand specification – either an explicit hourly series or a flat value."""

    series: list[float] | None = Field(
        None,
        description="Explicit hourly demand time series (MW). "
        "Length must match horizon_hours.",
    )
    flat_demand_mw: float | None = Field(
        None,
        ge=0,
        description="Constant demand for every hour (MW). "
        "Used only when 'series' is not provided.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"flat_demand_mw": 2000},
                {"series": [1800, 1750, 1700, 1680]},
            ]
        }
    }


class SimulationRequest(BaseModel):
    """Top-level simulation request."""

    scenario_name: str = Field(
        "default", description="Human-readable scenario label"
    )
    description: str = Field("", description="Optional longer description")
    horizon_hours: int = Field(
        24,
        ge=1,
        le=8760,
        description="Number of hours to simulate",
    )
    mode: SimulationMode = Field(
        SimulationMode.simple,
        description="'simple' uses a generation mix; 'advanced' accepts detailed generators",
    )
    demand: DemandProfile = Field(
        default_factory=DemandProfile,
        description="Demand / load specification",
    )
    simple_mix: SimpleMix | None = Field(
        None,
        description="Generation mix for simple mode",
    )
    generators: list[GeneratorSpec] | None = Field(
        None,
        description="Detailed generator list for advanced mode",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "scenario_name": "Base case",
                    "horizon_hours": 48,
                    "mode": "simple",
                    "demand": {"flat_demand_mw": 2000},
                    "simple_mix": {
                        "nuclear_mw": 2000,
                        "gas_mw": 1500,
                        "hydro_mw": 500,
                    },
                },
                {
                    "scenario_name": "Custom generators",
                    "horizon_hours": 24,
                    "mode": "advanced",
                    "demand": {"flat_demand_mw": 1500},
                    "generators": [
                        {
                            "technology": "nuclear",
                            "p_max": 1000,
                            "p_min": 500,
                            "marginal_cost": 5,
                            "lock_time": 24,
                        },
                        {
                            "technology": "gas",
                            "p_max": 800,
                            "p_min": 0,
                            "marginal_cost": 40,
                        },
                    ],
                },
            ]
        }
    }


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class GeneratorTimeSeries(BaseModel):
    """Per-generator time-series output."""

    generator_id: int = Field(..., description="Unique generator index")
    generator_name: str = Field(..., description="Display name")
    technology: str = Field(..., description="Technology type")
    dispatched_mw: list[float] = Field(
        ..., description="Dispatched power per interval (MW)"
    )
    curtailed_mw: list[float] = Field(
        ..., description="Curtailed power per interval (MW)"
    )
    is_online: list[bool] = Field(
        ..., description="Online status per interval"
    )


class TechnologyAggregate(BaseModel):
    """Aggregated dispatch per technology type."""

    technology: str
    total_dispatched_mwh: float = Field(
        ..., description="Sum of dispatched energy (MWh)"
    )
    capacity_factor: float = Field(
        ...,
        description="Ratio of actual output to maximum possible output",
    )
    installed_capacity_mw: float = Field(
        ..., description="Total installed capacity (MW)"
    )


class SummaryMetrics(BaseModel):
    """High-level simulation summary."""

    total_generation_mwh: float
    total_demand_mwh: float
    average_price: float
    max_price: float
    min_price: float
    total_energy_cost: float
    total_startup_cost: float
    total_shutdown_cost: float
    total_system_cost: float


class SimulationResponse(BaseModel):
    """Full simulation result payload."""

    scenario_name: str
    description: str
    horizon_hours: int
    mode: str
    intervals: list[int] = Field(
        ..., description="Interval indices (0-based hour offsets)"
    )
    price_series: list[float] = Field(
        ..., description="Market clearing price per interval (€/MWh)"
    )
    demand_series: list[float] = Field(
        ..., description="Load / demand per interval (MW)"
    )
    generator_series: list[GeneratorTimeSeries]
    technology_aggregates: list[TechnologyAggregate]
    summary: SummaryMetrics
    config_used: dict[str, Any] = Field(
        default_factory=dict,
        description="Expanded simulation configuration after applying defaults",
    )
    warnings: list[str] = Field(default_factory=list)
