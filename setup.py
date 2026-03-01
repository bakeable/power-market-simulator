from standard import *


class Setup:

    def __init__(self):
        self.__setup_load_schedule()

    def __setup_load_schedule(self):
        df = pd.read_csv("DK1 load.csv", parse_dates=["utc_timestamp"])
        df["utc_timestamp"] = df["utc_timestamp"].dt.tz_localize(None)
        df["date"] = df["utc_timestamp"].dt.normalize()
        df["hour"] = df["utc_timestamp"].dt.hour
        df["dow"] = df["utc_timestamp"].dt.day_of_week
        df["month"] = df["utc_timestamp"].dt.month
        df["year"] = df["utc_timestamp"].dt.year
        df["schedule"] = df.groupby(["date"]).ngroup()
        df["load"] = df["DK_1_load_actual_entsoe_transparency"]
        df["schedule_hour"] = df["schedule"].astype(str) + "_" + df["hour"].astype(str)
        df = df[["schedule", "hour", "schedule_hour", "load"]]
        df = df[df["load"].notna()].copy()
        self.load_schedule = df.copy()

        class Generator:
            def __init__(
                self,
                gen_type,
                p_min,
                p_max,
                mc,
                sc,
                lock_time,
                ramp_hour,
                online,
                locked,
                prev_dispatch=None,
            ):

                # Nameplate info
                self.id = 0
                self.gen_type = gen_type
                self.p_min = p_min
                self.p_max = p_max

                self.mc = mc
                self.sc = sc
                self.lock_time = lock_time
                self.ramp_hour = ramp_hour

                # Current state
                self.online = online
                self.locked = locked
                if self.online:
                    self.locked = False

                if prev_dispatch == None:
                    self.prev_dispatch = p_min

        self.Generator = Generator

    def units(
        self,
        n_units,
        type,
        p_min,
        p_max,
        mc,
        sc,
        ramp_hour,
        lock_time,
        online=False,
        locked=0,
    ):

        units = [
            self.Generator(
                type,
                p_min=p_min,
                p_max=p_max,
                mc=mc,
                sc=sc,
                lock_time=lock_time,
                ramp_hour=ramp_hour,
                online=online,
                locked=locked,
            )
            for _ in range(n_units)
        ]

        this_units_bids = pd.DataFrame(
            [
                {
                    "p_max": gen.p_max,
                    "p_min": gen.p_min,
                    "mc": gen.mc,
                    "sc": gen.sc,
                    "lock_time": gen.lock_time,
                    "ramp_hour": gen.ramp_hour,
                    "online": gen.online,
                    "locked": gen.locked,
                    "prev_dispatch": gen.p_min,
                    "max_cap": min(gen.p_min + gen.ramp_hour, gen.p_max),
                    "min_cap": p_min,
                    "type": gen.gen_type,
                    "dispatch": gen.p_min,
                }
                for gen in units
            ]
        )

        return this_units_bids

    def setup_generator_bids(self, units_list: list[pd.DataFrame]):

        bids = pd.DataFrame()
        bids = pd.concat(units_list)
        bids = bids.reset_index(drop=True)
        bids["id"] = bids.index
        bids = bids[[bids.columns[-1], *bids.columns[:-1]]].copy()
        self.original_bids = bids.copy()

