"""API integration tests using FastAPI TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


class TestHealthEndpoint:
    def test_health(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestSimulateEndpoint:
    def test_simple_mode_default_mix(self, client: TestClient):
        """Minimal simple-mode request with defaults."""
        resp = client.post(
            "/simulate",
            json={
                "scenario_name": "smoke_test",
                "horizon_hours": 24,
                "mode": "simple",
                "demand": {"flat_demand_mw": 2000},
                "simple_mix": {
                    "nuclear_mw": 2000,
                    "gas_mw": 1500,
                    "hydro_mw": 500,
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["scenario_name"] == "smoke_test"
        assert len(data["intervals"]) == 24
        assert len(data["price_series"]) == 24
        assert len(data["demand_series"]) == 24
        assert len(data["generator_series"]) > 0
        assert len(data["technology_aggregates"]) > 0

        # Invariants
        for gs in data["generator_series"]:
            assert len(gs["dispatched_mw"]) == 24
            assert all(d >= 0 for d in gs["dispatched_mw"])

    def test_advanced_mode(self, client: TestClient):
        """Advanced mode with explicit generators."""
        resp = client.post(
            "/simulate",
            json={
                "scenario_name": "advanced_test",
                "horizon_hours": 12,
                "mode": "advanced",
                "demand": {"flat_demand_mw": 800},
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
                        "p_max": 500,
                        "p_min": 0,
                        "marginal_cost": 40,
                    },
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "advanced"
        assert len(data["intervals"]) == 12
        assert data["summary"]["total_generation_mwh"] > 0
        assert data["summary"]["total_demand_mwh"] == pytest.approx(800 * 12)

    def test_advanced_mode_no_generators_fails(self, client: TestClient):
        resp = client.post(
            "/simulate",
            json={
                "mode": "advanced",
                "demand": {"flat_demand_mw": 1000},
                "generators": [],
            },
        )
        assert resp.status_code == 422

    def test_simple_mode_all_defaults(self, client: TestClient):
        """When no mix is provided, API should use defaults."""
        resp = client.post("/simulate", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["warnings"]) > 0

    def test_response_schema_stability(self, client: TestClient):
        """Ensure all expected top-level keys are present."""
        resp = client.post(
            "/simulate",
            json={
                "horizon_hours": 6,
                "mode": "simple",
                "demand": {"flat_demand_mw": 1000},
                "simple_mix": {"gas_mw": 2000},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        expected_keys = {
            "scenario_name",
            "description",
            "horizon_hours",
            "mode",
            "intervals",
            "price_series",
            "demand_series",
            "generator_series",
            "technology_aggregates",
            "summary",
            "config_used",
            "warnings",
        }
        assert expected_keys == set(data.keys())

    def test_demand_series_request(self, client: TestClient):
        """Provide explicit demand time series."""
        demand = [1000 + i * 10 for i in range(8)]
        resp = client.post(
            "/simulate",
            json={
                "horizon_hours": 8,
                "mode": "simple",
                "demand": {"series": demand},
                "simple_mix": {"gas_mw": 2000},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["demand_series"] == demand
