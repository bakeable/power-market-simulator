"""Merit-order electricity market simulation engine.

This module contains the core ``Market`` class that runs hour-by-hour
dispatch simulation with constraint resolution.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class Market:
    """Simulates merit-order dispatch and unit-commitment constraints.

    Parameters
    ----------
    initial_bids_state:
        DataFrame with one row per generator containing bid parameters.
    load_schedule:
        DataFrame with columns ``schedule``, ``hour``, ``schedule_hour``, ``load``.
    variable_bids:
        Optional time-varying bids (e.g. for solar/wind) with ``schedule``
        and ``hour`` columns in addition to the standard bid columns.
    """

    def __init__(
        self,
        initial_bids_state: pd.DataFrame,
        load_schedule: pd.DataFrame,
        variable_bids: pd.DataFrame | None = None,
    ) -> None:
        self.bids: pd.DataFrame = initial_bids_state.copy()
        self.load_schedule: pd.DataFrame = load_schedule
        self.variable_bids: pd.DataFrame | None = variable_bids
        self.logs: pd.DataFrame = pd.DataFrame()
        self.market_logs: pd.DataFrame = pd.DataFrame()
        self.market_log_slots: list[tuple[int, int]] | None = None
        self.undersupply: bool = False
        self.preferred_units: list[int] = []

        # Normalise data types
        self.bids["locked"] = self.bids["locked"].astype("int32")
        self.bids["lock_time"] = self.bids["lock_time"].astype("int32")

        # Runtime state (set per hour in start())
        self.load: float = 0.0
        self.schedule: int = 0
        self.hour: int = 0
        self.shutdown_costs: float = 0.0
        self.startup_costs: float = 0.0
        self.energy_costs: float = 0.0
        self.mcp: float = 0.0
        self.system_costs: float = 0.0
        self.event_squence: int = 0
        self.logging: bool = False
        self.constraints_found: bool = False
        self.curtailment_feasible: bool | None = None
        self.bids_now: pd.DataFrame = pd.DataFrame()

    def set_preferred_units(self, unit_ids: list[int] | None = None) -> None:
        self.preferred_units = unit_ids or []

    # ------------------------------------------------------------------
    # Main simulation loop
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Run the full simulation over every hour in the load schedule."""
        for row in self.load_schedule.itertuples(index=False):
            self.load = row.load
            self.schedule = row.schedule
            self.hour = row.hour
            self.shutdown_costs = 0.0
            self.startup_costs = 0.0
            self.energy_costs = 0.0

            self.event_squence = 0
            self.logging = False
            if self.market_log_slots is not None:
                if (self.schedule, self.hour) in self.market_log_slots:
                    self.logging = True

            # Enter market cycle
            self._market_cycle()
            if self.undersupply:
                return
            self._startup_units()
            self._calculate_cost_price()
            self._record_logs()

    # ------------------------------------------------------------------
    # Variable bids
    # ------------------------------------------------------------------

    def _add_variable_bids(self) -> None:
        if self.variable_bids is None:
            return
        schedule = self.schedule
        hour = self.hour
        vb = self.variable_bids

        mask = (vb["schedule"] == schedule) & (vb["hour"] == hour)
        vb = vb[mask]
        vb = vb.drop(columns=["schedule", "hour"])

        b = self.bids_now.copy()
        b = pd.concat([b, vb])
        self.bids_now = b.copy()

    # ------------------------------------------------------------------
    # Bid preparation
    # ------------------------------------------------------------------

    def _prepare_new_bids(self) -> None:
        b = self.bids_now.copy()
        b = b[~b["type"].isin(["solar", "wind"])]

        b["prev_dispatch"] = np.where(b["dispatch"] > 0, b["dispatch"], b["p_min"])
        b["max_cap"] = np.where(
            b["prev_dispatch"] + b["ramp_hour"] <= b["p_max"],
            b["prev_dispatch"] + b["ramp_hour"],
            b["p_max"],
        )
        b["min_cap"] = np.where(
            b["prev_dispatch"] - b["ramp_hour"] >= b["p_min"],
            b["prev_dispatch"] - b["ramp_hour"],
            b["p_min"],
        )
        self.bids_now = b.copy()

    # ------------------------------------------------------------------
    # Market logging helpers
    # ------------------------------------------------------------------

    def activate_market_logs(
        self, from_sch_hour: tuple[int, int], to_sch_hour: tuple[int, int]
    ) -> None:
        f = from_sch_hour
        t = to_sch_hour
        market_log_slots: list[tuple[int, int]] = []
        for schedule in range(f[0], t[0] + 1):
            start_hour = f[1] if schedule == f[0] else 0
            end_hour = t[1] if schedule == t[0] else 23
            for hour in range(start_hour, end_hour + 1):
                market_log_slots.append((schedule, hour))
        self.market_log_slots = market_log_slots

    def _log_market_log(self, event_label: str = "") -> None:
        if not self.logging:
            return

        b = self.bids_now.copy()
        b["event"] = event_label
        b["sequence"] = self.event_squence
        b["schedule"] = self.schedule
        b["hour"] = self.hour
        self.event_squence += 1
        self.market_logs = pd.concat([self.market_logs, b])

    # ------------------------------------------------------------------
    # Core market cycle
    # ------------------------------------------------------------------

    def _market_cycle(self) -> None:
        self.constraints_found = False
        self.bids_now = self.bids.copy()
        self._log_market_log("start")

        self._prepare_new_bids()
        self._add_variable_bids()
        self._update_locks()
        self._order_by_merit()
        if self.undersupply:
            return
        self._check_constraints()

        # 1. Shutdown non-preferred unit
        if self.constraints_found:
            self._shutdown_nonpreferred()
            self._order_by_merit()
            if self.undersupply:
                return
            self._check_constraints()

            # 2. Curtail in favour of marginal unit
            if self.constraints_found:
                self._curtailment_protocol()

                # 3. If not feasible, shutdown marginal until no more constraint
                if not self.curtailment_feasible:
                    while self.constraints_found:
                        self._shutdown_marginal_only()
                        self._order_by_merit()
                        if self.undersupply:
                            return
                        self._check_constraints()

        # Clean up temporary columns
        self.bids_now = self.bids_now.drop(
            columns=["constrained", "curtail", "redispatch"], errors="ignore"
        )

    # ------------------------------------------------------------------
    # Lock management
    # ------------------------------------------------------------------

    def _update_locks(self) -> None:
        b = self.bids_now.copy()
        b["locked"] = np.where(b["locked"] - 1 >= 0, b["locked"] - 1, b["locked"])
        self.bids_now = b
        self._log_market_log("updating_locks")

    # ------------------------------------------------------------------
    # Merit-order dispatch
    # ------------------------------------------------------------------

    def _order_by_merit(self) -> None:
        load = self.load
        b = self.bids_now.copy()
        b = b.sort_values(["locked", "mc"])

        self.undersupply = False

        # Check if load exceeds available capacity
        if load > b[b["locked"] == 0]["max_cap"].sum():
            self.undersupply = True
            return

        dispatches: list[float] = []
        leftovers: list[float] = []

        leftover = load
        for row in b.itertuples(index=False):
            dispatch = min(leftover, row.max_cap)
            dispatches.append(dispatch)
            leftover = leftover - dispatch
            leftovers.append(leftover)

        b["dispatch"] = dispatches
        b["leftover"] = leftovers

        self.bids_now = b
        self._log_market_log("merit_ordering")

    # ------------------------------------------------------------------
    # Constraint checking
    # ------------------------------------------------------------------

    def _check_constraints(self) -> None:
        b = self.bids_now.copy()
        active_cond = b["dispatch"] > 0

        b["constrained"] = 0

        # 1. Most offline units are not constraints.
        b["constrained"] = np.where(b["online"] == False, 0, b["constrained"])  # noqa: E712

        # 2. Any online unit NOT DISPATCHED is a constraint.
        b["constrained"] = np.where(
            (b["online"] == True) & ~(active_cond), 1, b["constrained"]  # noqa: E712
        )

        # 3. Any unit DISPATCHED and outside its limits is a constraint.
        b["constrained"] = np.where(
            (b["dispatch"] < b["min_cap"]) & active_cond, 1, b["constrained"]
        )
        b["constrained"] = np.where(
            (b["dispatch"] > b["max_cap"]) & active_cond, 1, b["constrained"]
        )

        # 4. Any unit DISPATCHED and LOCKED is a constraint.
        b["constrained"] = np.where(
            (b["locked"] > 0) & active_cond, 1, b["constrained"]
        )

        self.constraints_found = b["constrained"].sum() > 0
        self.bids_now = b.copy()
        self._log_market_log("checking_constraint")

    # ------------------------------------------------------------------
    # Constraint resolution
    # ------------------------------------------------------------------

    def _shutdown_nonpreferred(self) -> None:
        preferred_ids = self.preferred_units

        b = self.bids_now.copy()
        mask = (b["constrained"] == 1) & (~b["id"].isin(preferred_ids) & (b["dispatch"] == 0))
        b.loc[mask, "online"] = False
        b.loc[mask, "locked"] = b.loc[mask, "lock_time"]
        b.loc[mask, "prev_dispatch"] = b.loc[mask, "p_min"]
        b.loc[mask, "min_cap"] = b.loc[mask, "p_min"]
        b.loc[mask, "max_cap"] = b.loc[mask, "prev_dispatch"] + b.loc[mask, "ramp_hour"]
        b["max_cap"] = np.where(b["max_cap"] > b["p_max"], b["p_max"], b["max_cap"])
        shutdown_cost = b[mask]["sc"].sum()
        self.shutdown_costs += shutdown_cost
        self.bids_now = b.copy()
        self._log_market_log("shutting_down_nonpreferred")

    def _curtailment_protocol(self) -> None:
        load = self.load
        b = self.bids_now.copy()
        b["curtail"] = np.where((b["dispatch"] > 0) & (b["constrained"] == 0), 1, 0)
        retained_power = b[b["constrained"] == 1]["min_cap"].sum()
        final_curtailed_power = load - retained_power
        initial_power_to_curtail = b[b["curtail"] == 1]["dispatch"].sum()
        if initial_power_to_curtail != 0:
            curtailment_factor = final_curtailed_power / initial_power_to_curtail
        else:
            curtailment_factor = 0

        b["redispatch"] = np.where(
            b["dispatch"] * curtailment_factor >= b["min_cap"],
            b["dispatch"] * curtailment_factor,
            b["min_cap"],
        )
        b["redispatch"] = np.where(
            (b["constrained"] == 0) & (b["curtail"] == 0), 0, b["redispatch"]
        )

        self.curtailment_feasible = None

        total_redispatch = b["redispatch"].sum()
        tol = 1e-6

        if abs(total_redispatch - load) <= tol:
            b["dispatch"] = b["redispatch"]
            self.curtailment_feasible = True
            self.bids_now = b.copy()
        else:
            b["dispatch"] = b["redispatch"]
            self.curtailment_feasible = False
            self.bids_now = b.copy()

        self._log_market_log("attempting_curtailment")

    def _shutdown_marginal_only(self) -> None:
        b = self.bids_now.copy()
        marginal_mask = (b["dispatch"] > 0) & (b["dispatch"].shift(-1) <= 0)

        # 1. If unit is currently online, turn it off with lockdown rules.
        mask = (b["online"] == True) & marginal_mask  # noqa: E712
        b.loc[mask, "online"] = False
        b.loc[mask, "locked"] = b.loc[mask, "lock_time"]
        b.loc[mask, "prev_dispatch"] = b.loc[mask, "p_min"]
        b.loc[mask, "min_cap"] = b.loc[mask, "p_min"]
        b.loc[mask, "max_cap"] = b.loc[mask, "prev_dispatch"] + b.loc[mask, "ramp_hour"]
        shutdown_cost = b[mask]["sc"].sum()
        self.shutdown_costs += shutdown_cost

        # 2. If unit is currently offline and not locked, set lock to 1.
        mask = (b["online"] == False) & marginal_mask & (b["locked"] == 0)  # noqa: E712
        b.loc[mask, "online"] = False
        b.loc[mask, "locked"] = 1
        b.loc[mask, "prev_dispatch"] = b.loc[mask, "p_min"]
        b.loc[mask, "min_cap"] = b.loc[mask, "p_min"]
        b.loc[mask, "max_cap"] = b.loc[mask, "prev_dispatch"] + b.loc[mask, "ramp_hour"]
        shutdown_cost = b[mask]["sc"].sum()
        self.shutdown_costs += shutdown_cost

        self.bids_now = b.copy()
        self._log_market_log("shutting_down_marginal_unit")

    # ------------------------------------------------------------------
    # Post-dispatch
    # ------------------------------------------------------------------

    def _startup_units(self) -> None:
        b = self.bids_now.copy()
        mask = (b["dispatch"] > 0) & (b["online"] == False)  # noqa: E712
        startup_cost = b[mask]["sc"].sum()
        b.loc[mask, "online"] = True
        self.startup_costs += startup_cost
        self.bids_now = b.copy()

    def _calculate_cost_price(self) -> None:
        b = self.bids_now.copy()
        dispatched = b[b["dispatch"] > 0]
        self.mcp = dispatched["mc"].max() if not dispatched.empty else 0.0
        self.energy_costs = dispatched["dispatch"].sum() * self.mcp
        self.system_costs = self.energy_costs + self.shutdown_costs + self.startup_costs

    def _record_logs(self) -> None:
        b = self.bids_now.copy()

        b["schedule"] = self.schedule
        b["hour"] = self.hour
        b["load"] = self.load
        b["mcp"] = self.mcp
        b["energy_costs"] = self.energy_costs
        b["shutdown_costs"] = self.shutdown_costs
        b["startup_costs"] = self.startup_costs
        b["system_cost"] = self.system_costs
        self.logs = pd.concat([self.logs, b])

        standard_cols = [
            "id",
            "p_max",
            "p_min",
            "mc",
            "sc",
            "lock_time",
            "ramp_hour",
            "online",
            "locked",
            "prev_dispatch",
            "max_cap",
            "min_cap",
            "type",
            "dispatch",
        ]

        # Rewrite bids
        self.bids_now = b[standard_cols].copy()
        self.bids = self.bids_now.copy()
