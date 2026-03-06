"""Generator setup and load schedule configuration.

This module provides the ``Setup`` class for loading demand data and
defining generator units as bid DataFrames consumable by the ``Market``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np  # noqa: F401 – used implicitly via pandas operations
import pandas as pd

# Default path to bundled load data
_DEFAULT_CSV = Path(__file__).resolve().parents[3] / "data" / "DK1_load.csv"


class Setup:
    """Prepares load schedules and generator bid tables for the Market engine.

    Parameters
    ----------
    csv_path:
        Path to the hourly load CSV.  Falls back to the bundled DK1 data.
    """

    def __init__(self, csv_path: str | Path | None = None) -> None:
        self.load_schedule: pd.DataFrame = pd.DataFrame()
        self.original_bids: pd.DataFrame = pd.DataFrame()
        self._setup_load_schedule(csv_path or _DEFAULT_CSV)

    # ------------------------------------------------------------------
    # Load schedule
    # ------------------------------------------------------------------

    def _setup_load_schedule(self, csv_path: str | Path) -> None:
        df = pd.read_csv(csv_path, parse_dates=["utc_timestamp"])
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

    # ------------------------------------------------------------------
    # Load schedule from explicit demand list
    # ------------------------------------------------------------------

    @staticmethod
    def load_schedule_from_list(demand: list[float]) -> pd.DataFrame:
        """Create a load schedule DataFrame from an explicit hourly demand list.

        Each 24-hour block is assigned a sequential *schedule* index and
        the position within that block becomes the *hour*.
        """
        n = len(demand)
        schedules = [i // 24 for i in range(n)]
        hours = [i % 24 for i in range(n)]
        df = pd.DataFrame(
            {
                "schedule": schedules,
                "hour": hours,
                "schedule_hour": [f"{s}_{h}" for s, h in zip(schedules, hours)],
                "load": demand,
            }
        )
        return df

    # ------------------------------------------------------------------
    # Generator helpers
    # ------------------------------------------------------------------

    def units(
        self,
        n_units: int,
        type: str,
        p_min: float,
        p_max: float,
        mc: float,
        sc: float,
        ramp_hour: float,
        lock_time: int,
        online: bool = False,
        locked: int = 0,
    ) -> pd.DataFrame:
        """Create a bid DataFrame for *n_units* identical generators."""
        rows: list[dict[str, Any]] = []
        for _ in range(n_units):
            rows.append(
                {
                    "p_max": p_max,
                    "p_min": p_min,
                    "mc": mc,
                    "sc": sc,
                    "lock_time": lock_time,
                    "ramp_hour": ramp_hour,
                    "online": online,
                    "locked": locked,
                    "prev_dispatch": p_min,
                    "max_cap": min(p_min + ramp_hour, p_max),
                    "min_cap": p_min,
                    "type": type,
                    "dispatch": p_min,
                }
            )
        return pd.DataFrame(rows)

    def setup_generator_bids(self, units_list: list[pd.DataFrame]) -> None:
        """Concatenate unit DataFrames and assign sequential IDs."""
        bids = pd.concat(units_list, ignore_index=True)
        bids["id"] = bids.index
        # Move id to first column
        cols = ["id"] + [c for c in bids.columns if c != "id"]
        self.original_bids = bids[cols].copy()
