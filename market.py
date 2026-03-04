from standard import *


class Market:
    def __init__(
        self,
        initial_bids_state: pd.DataFrame,
        load_schedule: pd.DataFrame,
        variable_bids: pd.DataFrame | None = None,
    ):
        self.bids = initial_bids_state
        self.load_schedule = load_schedule
        self.variable_bids = variable_bids
        self.logs = pd.DataFrame()
        self.market_logs = pd.DataFrame()
        self.market_log_slots = None
        self.undersupply = False
        self.preferred_units = []

        # to normalize data type
        self.bids["locked"] = self.bids["locked"].astype("int32")
        self.bids["lock_time"] = self.bids["lock_time"].astype("int32")

    def set_preferred_units(self, unit_ids: list = []):
        self.preferred_units = unit_ids

    def start(self):

        # Main loop over each hour begins here

        for row in self.load_schedule.itertuples(index=False):
            self.load = row.load
            self.schedule = row.schedule
            self.hour = row.hour
            self.shutdown_costs = 0
            self.startup_costs = 0
            self.energy_costs = 0

            self.event_squence = 0
            self.logging = False
            if self.market_log_slots != None:
                if (self.schedule, self.hour) in self.market_log_slots:
                    self.logging = True

            # Enter into the market cycle
            self.__market_cycle()
            if self.undersupply:
                print("Load exceeds capacity!")
                return
            self.__startup_units()
            self.__calculate_cost_price()
            self.__record_logs()

    def __add_variable_bids(self):
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

    def __prepare_new_bids(self):
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

    def activate_market_logs(self, from_sch_hour: tuple, to_sch_hour: tuple):
        f = from_sch_hour
        t = to_sch_hour
        market_log_slots = []
        for schedule in range(f[0], t[0] + 1):
            start_hour = f[1] if schedule == f[0] else 0
            end_hour = t[1] if schedule == t[0] else 23
            for hour in range(start_hour, end_hour + 1):
                market_log_slots.append((schedule, hour))
        self.market_log_slots = market_log_slots

    def __log_market_log(self, event_label=""):
        if not self.logging:
            return

        b = self.bids_now.copy()
        b["event"] = event_label
        b["sequence"] = self.event_squence
        b["schedule"] = self.schedule
        b["hour"] = self.hour
        self.event_squence += 1
        self.market_logs = pd.concat([self.market_logs, b])

    def __market_cycle(self):

        self.constraints_found = False
        self.bids_now = self.bids.copy()
        self.__log_market_log("start")

        self.__prepare_new_bids()
        self.__add_variable_bids()
        self.__update_locks()
        self.__order_by_merit()
        if self.undersupply:
            return
        self.__check_constraints()

        # market operator / system operator must
        # decide what to do with constraints

        # 1. shutdown non-preferred unit
        if self.constraints_found:
            self.__shutdown_nonpreferred()
            self.__order_by_merit()
            if self.undersupply:
                return
            self.__check_constraints()

            # 2. curtail in favor of marginal unit
            if self.constraints_found:
                self.__curtailment_protocol()

                # 3. if that's not feasible, shutdown marginal until no more constraint
                if not self.curtailment_feasible:
                    while self.constraints_found:
                        self.__shutdown_marginal_only()
                        self.__order_by_merit()
                        if self.undersupply:
                            return
                        self.__check_constraints()

        # clean up temporary columns
        self.bids_now = self.bids_now.drop(
            columns=["constrained", "curtail", "redispatch"], errors="ignore"
        )

    def __update_locks(self):
        b = self.bids_now.copy()
        b["locked"] = np.where(b["locked"] - 1 >= 0, b["locked"] - 1, b["locked"])
        self.bids_now = b
        self.__log_market_log("updating_locks")

    def __order_by_merit(self):
        load = self.load
        b = self.bids_now.copy()
        b = b.sort_values(["locked", "mc"])

        self.undersupply = False

        # Check if load exceeds available capacity
        # If so, break the market cycle

        if load > b[b["locked"] == 0]["max_cap"].sum():
            self.undersupply = True
            return

        dispatches = []
        leftovers = []

        leftover = load
        for row in b.itertuples(index=False):
            dispatch = min(leftover, row.max_cap)
            dispatches.append(dispatch)
            leftover = leftover - dispatch
            leftovers.append(leftover)

            if leftover <= 0:
                pass

        b["dispatch"] = dispatches
        b["leftover"] = leftovers

        self.bids_now = b
        self.__log_market_log("merit_ordering")

    def __check_constraints(self):
        b = self.bids_now.copy()
        active_cond = b["dispatch"] > 0

        b["constrained"] = 0

        # 1. Most offline units are not constraints.
        b["constrained"] = np.where(b["online"] == False, 0, b["constrained"])

        # 2. Any online unit NOT DISPATCHED is a constraint.
        b["constrained"] = np.where(
            (b["online"] == True) & ~(active_cond), 1, b["constrained"]
        )

        # 3. Any unit that is DISPATCHED (online or offline)
        # and is higher or lower than its limits is a constraint.
        b["constrained"] = np.where(
            (b["dispatch"] < b["min_cap"]) & active_cond, 1, b["constrained"]
        )
        b["constrained"] = np.where(
            (b["dispatch"] > b["max_cap"]) & active_cond, 1, b["constrained"]
        )

        # 3. Any unit that is DISPATCHED and LOCKED is a constraint.
        b["constrained"] = np.where(
            (b["locked"] > 0) & active_cond, 1, b["constrained"]
        )

        if b["constrained"].sum() > 0:
            self.constraints_found = True
        else:
            self.constraints_found = False

        self.bids_now = b.copy()
        self.__log_market_log("checking_constraint")

    def __shutdown_nonpreferred(self):

        preferred_ids = self.preferred_units

        b = self.bids_now.copy()
        mask = (b["constrained"] == 1) & (
            ~b["id"].isin(preferred_ids) & (b["dispatch"] == 0)
        )
        b.loc[mask, "online"] = False
        b.loc[mask, "locked"] = b.loc[mask, "lock_time"]
        b.loc[mask, "prev_dispatch"] = b.loc[mask, "p_min"]
        b.loc[mask, "min_cap"] = b.loc[mask, "p_min"]
        b.loc[mask, "max_cap"] = b.loc[mask, "prev_dispatch"] + b.loc[mask, "ramp_hour"]
        b["max_cap"] = np.where(b["max_cap"] > b["p_max"], b["p_max"], b["max_cap"])
        shutdown_cost = b[mask]["sc"].sum()
        self.shutdown_costs += shutdown_cost
        self.bids_now = b.copy()
        self.__log_market_log("shutting_down_nonpreferred")

    def __curtailment_protocol(self):
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
        tol = 1e-6  # prevents floating point comparison errors e.g. 1751.4699999999998 < 1751.47

        if abs(total_redispatch - load) <= tol:
            b["dispatch"] = b["redispatch"]
            self.curtailment_feasible = True
            self.bids_now = b.copy()
        else:
            b["dispatch"] = b["redispatch"]
            self.curtailment_feasible = False
            self.bids_now = b.copy()

        self.__log_market_log("attempting_curtailment")

    def __shutdown_marginal_only(self):
        b = self.bids_now.copy()
        marginal_mask = (b["dispatch"] > 0) & (b["dispatch"].shift(-1) <= 0)

        # 1. If the unit is currently online, turn it off with lockdown rules.
        mask = (b["online"] == True) & marginal_mask
        b.loc[mask, "online"] = False
        b.loc[mask, "locked"] = b.loc[mask, "lock_time"]
        b.loc[mask, "prev_dispatch"] = b.loc[mask, "p_min"]
        b.loc[mask, "min_cap"] = b.loc[mask, "p_min"]
        b.loc[mask, "max_cap"] = b.loc[mask, "prev_dispatch"] + b.loc[mask, "ramp_hour"]
        shutdown_cost = b[mask]["sc"].sum()
        self.shutdown_costs += shutdown_cost

        # 1. If the unit is currently offline and not locked, set lock to 1 to prevent them from bidding this round.
        mask = (b["online"] == False) & marginal_mask & (b["locked"] == 0)
        b.loc[mask, "online"] = False
        b.loc[mask, "locked"] = 1
        b.loc[mask, "prev_dispatch"] = b.loc[mask, "p_min"]
        b.loc[mask, "min_cap"] = b.loc[mask, "p_min"]
        b.loc[mask, "max_cap"] = b.loc[mask, "prev_dispatch"] + b.loc[mask, "ramp_hour"]
        shutdown_cost = b[mask]["sc"].sum()
        self.shutdown_costs += shutdown_cost

        self.bids_now = b.copy()
        self.__log_market_log("shutting_down_marginal_unit")

    def __startup_units(self):
        b = self.bids_now.copy()
        mask = (b["dispatch"] > 0) & (b["online"] == False)
        startup_cost = b[mask]["sc"].sum()
        b.loc[mask, "online"] = True
        self.startup_costs += startup_cost
        self.bids_now = b.copy()

    def __calculate_cost_price(self):
        b = self.bids_now.copy()
        self.mcp = b[b["dispatch"] > 0]["mc"].max()
        self.energy_costs = b[b["dispatch"] > 0]["dispatch"].sum() * self.mcp
        self.system_costs = self.energy_costs + self.shutdown_costs + self.startup_costs

    def __record_logs(self):
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

        # rewrite bids
        self.bids_now = b[standard_cols].copy()
        self.bids = self.bids_now.copy()
