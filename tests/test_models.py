"""Schema validation tests for Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.models import (
    DemandProfile,
    GeneratorSpec,
    HistoricalForecastConfig,
    SimpleMix,
    SimulationRequest,
)


class TestSimpleMix:
    def test_defaults_to_zero(self):
        mix = SimpleMix()
        assert mix.nuclear_mw == 0
        assert mix.gas_mw == 0

    def test_rejects_negative(self):
        with pytest.raises(ValidationError):
            SimpleMix(nuclear_mw=-100)


class TestGeneratorSpec:
    def test_valid_generator(self):
        g = GeneratorSpec(technology="gas", p_max=500, marginal_cost=40)
        assert g.p_max == 500

    def test_rejects_zero_p_max(self):
        with pytest.raises(ValidationError):
            GeneratorSpec(technology="gas", p_max=0, marginal_cost=40)

    def test_defaults_applied(self):
        g = GeneratorSpec(technology="nuclear", p_max=1000, marginal_cost=5)
        assert g.p_min == 0
        assert g.shutdown_cost == 0
        assert g.ramp_rate == 1000
        assert g.lock_time == 0
        assert g.online is False


class TestDemandProfile:
    def test_flat_demand(self):
        d = DemandProfile(flat_demand_mw=2000)
        assert d.flat_demand_mw == 2000
        assert d.series is None

    def test_series_demand(self):
        d = DemandProfile(series=[100, 200, 300])
        assert d.series == [100, 200, 300]

    def test_historical_forecast_demand(self):
        d = DemandProfile(historical_forecast=HistoricalForecastConfig())
        assert d.historical_forecast is not None
        assert d.series is None
        assert d.flat_demand_mw is None

    def test_historical_forecast_with_params(self):
        cfg = HistoricalForecastConfig(start_hour=8, start_dow=1, start_month=6)
        d = DemandProfile(historical_forecast=cfg)
        assert d.historical_forecast.start_hour == 8
        assert d.historical_forecast.start_dow == 1
        assert d.historical_forecast.start_month == 6


class TestHistoricalForecastConfig:
    def test_defaults(self):
        cfg = HistoricalForecastConfig()
        assert cfg.start_hour == 0
        assert cfg.start_dow == 0
        assert cfg.start_month == 1

    def test_rejects_invalid_hour(self):
        with pytest.raises(ValidationError):
            HistoricalForecastConfig(start_hour=24)

    def test_rejects_invalid_dow(self):
        with pytest.raises(ValidationError):
            HistoricalForecastConfig(start_dow=7)

    def test_rejects_invalid_month_zero(self):
        with pytest.raises(ValidationError):
            HistoricalForecastConfig(start_month=0)

    def test_rejects_invalid_month_thirteen(self):
        with pytest.raises(ValidationError):
            HistoricalForecastConfig(start_month=13)


class TestSimulationRequest:
    def test_simple_mode_defaults(self):
        req = SimulationRequest(
            scenario_name="test",
            mode="simple",
            demand=DemandProfile(flat_demand_mw=1000),
            simple_mix=SimpleMix(nuclear_mw=2000),
        )
        assert req.mode.value == "simple"
        assert req.horizon_hours == 24

    def test_advanced_mode(self):
        req = SimulationRequest(
            scenario_name="adv",
            mode="advanced",
            demand=DemandProfile(flat_demand_mw=1000),
            generators=[
                GeneratorSpec(technology="gas", p_max=500, marginal_cost=40),
            ],
        )
        assert req.mode.value == "advanced"
        assert len(req.generators) == 1

    def test_horizon_bounds(self):
        with pytest.raises(ValidationError):
            SimulationRequest(horizon_hours=0)
        with pytest.raises(ValidationError):
            SimulationRequest(horizon_hours=9000)
