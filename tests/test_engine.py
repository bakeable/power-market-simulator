"""Unit tests for the core simulation engine."""

from __future__ import annotations

import pandas as pd
import pytest

from power_market_simulator.engine.forecast import LoadForecaster
from power_market_simulator.engine.market import Market
from power_market_simulator.engine.setup import Setup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_simple_scenario(
    demand: list[float],
    generators: list[dict],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (bids, load_schedule) for a minimal scenario."""
    setup = Setup.__new__(Setup)
    setup.load_schedule = pd.DataFrame()
    setup.original_bids = pd.DataFrame()

    frames = []
    for g in generators:
        frames.append(
            setup.units(
                n_units=g.get("n", 1),
                type=g["type"],
                p_min=g.get("p_min", 0),
                p_max=g["p_max"],
                mc=g["mc"],
                sc=g.get("sc", 0),
                ramp_hour=g.get("ramp_hour", 10000),
                lock_time=g.get("lock_time", 0),
                online=g.get("online", False),
                locked=g.get("locked", 0),
            )
        )
    bids = pd.concat(frames, ignore_index=True)
    bids["id"] = bids.index
    cols = ["id"] + [c for c in bids.columns if c != "id"]
    bids = bids[cols]

    load_schedule = Setup.load_schedule_from_list(demand)
    return bids, load_schedule


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSetup:
    def test_load_schedule_from_list(self):
        demand = [100.0] * 48
        ls = Setup.load_schedule_from_list(demand)
        assert len(ls) == 48
        assert list(ls.columns) == ["schedule", "hour", "schedule_hour", "load"]
        assert ls["schedule"].iloc[0] == 0
        assert ls["schedule"].iloc[24] == 1
        assert ls["hour"].iloc[0] == 0
        assert ls["hour"].iloc[23] == 23
        assert ls["hour"].iloc[24] == 0

    def test_units_creates_correct_shape(self):
        setup = Setup.__new__(Setup)
        setup.load_schedule = pd.DataFrame()
        setup.original_bids = pd.DataFrame()
        frame = setup.units(
            n_units=3, type="gas", p_min=0, p_max=500,
            mc=40, sc=0, ramp_hour=1000, lock_time=0,
        )
        assert len(frame) == 3
        assert "p_max" in frame.columns
        assert (frame["p_max"] == 500).all()


class TestMarketBasic:
    def test_single_generator_single_hour(self):
        """One generator, one hour, demand within capacity."""
        bids, ls = _make_simple_scenario(
            demand=[500.0],
            generators=[{"type": "gas", "p_max": 1000, "mc": 40}],
        )
        m = Market(bids, ls)
        m.start()
        assert not m.undersupply
        assert not m.logs.empty
        assert len(m.logs) == 1
        assert m.logs["dispatch"].iloc[0] == pytest.approx(500.0)

    def test_merit_order(self):
        """Cheapest generator should be dispatched first."""
        bids, ls = _make_simple_scenario(
            demand=[600.0],
            generators=[
                {"type": "gas", "p_max": 500, "mc": 40},
                {"type": "nuclear", "p_max": 500, "mc": 5},
            ],
        )
        m = Market(bids, ls)
        m.start()
        assert not m.undersupply
        # Nuclear (mc=5) should be fully dispatched, gas fills remainder
        nuclear_row = m.logs[m.logs["type"] == "nuclear"]
        gas_row = m.logs[m.logs["type"] == "gas"]
        assert nuclear_row["dispatch"].iloc[0] == pytest.approx(500.0)
        assert gas_row["dispatch"].iloc[0] == pytest.approx(100.0)

    def test_undersupply_detected(self):
        """If demand > total capacity, simulation should flag undersupply."""
        bids, ls = _make_simple_scenario(
            demand=[2000.0],
            generators=[{"type": "gas", "p_max": 500, "mc": 40}],
        )
        m = Market(bids, ls)
        m.start()
        assert m.undersupply

    def test_multi_hour_simulation(self):
        """Simulation should produce one log row per generator per hour."""
        n_hours = 24
        bids, ls = _make_simple_scenario(
            demand=[1000.0] * n_hours,
            generators=[
                {"type": "nuclear", "p_max": 800, "mc": 5},
                {"type": "gas", "p_max": 500, "mc": 40},
            ],
        )
        m = Market(bids, ls)
        m.start()
        assert not m.undersupply
        # 2 generators × 24 hours = 48 rows
        assert len(m.logs) == 2 * n_hours

    def test_nonnegative_dispatch(self):
        """All dispatch values must be non-negative."""
        bids, ls = _make_simple_scenario(
            demand=[800.0] * 10,
            generators=[
                {"type": "nuclear", "p_max": 500, "mc": 5, "online": True},
                {"type": "gas", "p_max": 500, "mc": 40},
            ],
        )
        m = Market(bids, ls)
        m.start()
        assert (m.logs["dispatch"] >= 0).all()

    def test_mcp_is_max_dispatched_mc(self):
        """Market clearing price should equal the highest mc of dispatched units."""
        bids, ls = _make_simple_scenario(
            demand=[600.0],
            generators=[
                {"type": "nuclear", "p_max": 500, "mc": 5},
                {"type": "gas", "p_max": 500, "mc": 40},
            ],
        )
        m = Market(bids, ls)
        m.start()
        assert m.mcp == pytest.approx(40.0)

    def test_price_series_length_matches_horizon(self):
        """Number of unique MCP values should equal the number of hours."""
        n_hours = 12
        bids, ls = _make_simple_scenario(
            demand=[500.0] * n_hours,
            generators=[{"type": "gas", "p_max": 1000, "mc": 40}],
        )
        m = Market(bids, ls)
        m.start()
        unique_intervals = m.logs.drop_duplicates(subset=["schedule", "hour"])
        assert len(unique_intervals) == n_hours


class TestLoadForecaster:
    """Tests for the LoadForecaster class."""

    def test_forecast_length(self):
        """Forecast should return exactly horizon_hours values."""
        forecaster = LoadForecaster()
        result = forecaster.forecast(horizon_hours=24)
        assert len(result) == 24

    def test_forecast_positive_values(self):
        """All forecasted demand values should be positive MW figures."""
        forecaster = LoadForecaster()
        result = forecaster.forecast(horizon_hours=48)
        assert all(v > 0 for v in result), "Expected all demand values to be positive"

    def test_forecast_single_hour(self):
        """A one-hour forecast should return a single value."""
        forecaster = LoadForecaster()
        result = forecaster.forecast(horizon_hours=1, start_hour=12, start_dow=0, start_month=6)
        assert len(result) == 1

    def test_forecast_varies_by_start(self):
        """Forecasts starting at different times should produce different profiles."""
        forecaster = LoadForecaster()
        night = forecaster.forecast(horizon_hours=1, start_hour=3, start_dow=0, start_month=1)
        midday = forecaster.forecast(horizon_hours=1, start_hour=12, start_dow=0, start_month=1)
        # Night load should generally be lower than midday load in power systems
        assert night != midday

    def test_forecast_varies_by_month(self):
        """Winter and summer forecasts should differ due to seasonal load patterns."""
        forecaster = LoadForecaster()
        winter = forecaster.forecast(horizon_hours=24, start_hour=0, start_dow=0, start_month=1)
        summer = forecaster.forecast(horizon_hours=24, start_hour=0, start_dow=0, start_month=7)
        assert winter != summer

    def test_forecast_invalid_horizon(self):
        """horizon_hours < 1 should raise ValueError."""
        forecaster = LoadForecaster()
        with pytest.raises(ValueError, match="horizon_hours"):
            forecaster.forecast(horizon_hours=0)

    def test_forecast_invalid_start_hour(self):
        """start_hour outside [0, 23] should raise ValueError."""
        forecaster = LoadForecaster()
        with pytest.raises(ValueError, match="start_hour"):
            forecaster.forecast(horizon_hours=1, start_hour=24)

    def test_forecast_invalid_start_dow(self):
        """start_dow outside [0, 6] should raise ValueError."""
        forecaster = LoadForecaster()
        with pytest.raises(ValueError, match="start_dow"):
            forecaster.forecast(horizon_hours=1, start_dow=7)

    def test_forecast_invalid_start_month(self):
        """start_month outside [1, 12] should raise ValueError."""
        forecaster = LoadForecaster()
        with pytest.raises(ValueError, match="start_month"):
            forecaster.forecast(horizon_hours=1, start_month=13)

    def test_forecast_week_wraps(self):
        """Forecasting beyond 7 days should wrap day-of-week correctly."""
        forecaster = LoadForecaster()
        # 168 hours = 1 week; starting Monday should end on Sunday
        result = forecaster.forecast(horizon_hours=168, start_hour=0, start_dow=0, start_month=1)
        assert len(result) == 168

    def test_forecast_month_advances_over_long_horizon(self):
        """A multi-month forecast should use different month averages over time."""
        forecaster = LoadForecaster()
        # 720 hours ≈ 30 days; starting in January should eventually use Feb averages
        result = forecaster.forecast(horizon_hours=720, start_hour=0, start_dow=0, start_month=1)
        assert len(result) == 720
        # The first 24h (January) and last 24h (around February) should differ
        # because seasonal averages differ between months
        first_day = result[:24]
        last_day = result[696:]
        assert first_day != last_day

    def test_forecaster_usable_as_demand_in_simulation(self):
        """A forecasted demand list should drive a full market simulation."""
        forecaster = LoadForecaster()
        demand = forecaster.forecast(horizon_hours=24, start_hour=0, start_dow=0, start_month=1)
        assert len(demand) == 24

        bids, ls = _make_simple_scenario(
            demand=demand,
            generators=[{"type": "gas", "p_max": 5000, "mc": 40}],
        )
        m = Market(bids, ls)
        m.start()
        assert not m.logs.empty
        assert len(m.logs) == 24
