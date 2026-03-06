"""Schema validation tests for Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.models import (
    DemandProfile,
    GeneratorSpec,
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
