"""Load forecasting from historical data.

This module provides the :class:`LoadForecaster` class, which derives
typical hourly demand profiles from the bundled DK1 historical load CSV
and uses them to generate a demand forecast for any requested horizon.

The forecast is based on **historical averages** grouped by
*(hour-of-day, day-of-week, month)*, giving a seasonally-aware typical
load profile.  The result is a deterministic "what if" demand series –
not a probabilistic or machine-learning-based prediction.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# Default path to bundled load data
_DEFAULT_CSV = Path(__file__).resolve().parents[3] / "data" / "DK1_load.csv"

# Day-of-week cycles: 0=Monday … 6=Sunday
_DAYS_IN_WEEK = 7
# Months: 1 … 12
_MONTHS_IN_YEAR = 12


class LoadForecaster:
    """Generate an hourly demand forecast from historical load data.

    The forecaster pre-computes a lookup table of **mean load** for every
    combination of *(hour_of_day, day_of_week, month)* using the provided
    CSV file.  Forecasting then simply walks the calendar forward from the
    specified start point and looks up the corresponding average.

    Parameters
    ----------
    csv_path:
        Path to an ENTSO-E formatted hourly load CSV with columns
        ``utc_timestamp`` and ``DK_1_load_actual_entsoe_transparency``.
        Defaults to the bundled DK1 dataset.

    Raises
    ------
    ValueError
        If the CSV does not contain enough valid data to build the profile.
    """

    def __init__(self, csv_path: str | Path | None = None) -> None:
        self._profile: pd.DataFrame = pd.DataFrame()
        self._load_profile(csv_path or _DEFAULT_CSV)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_profile(self, csv_path: str | Path) -> None:
        """Read the CSV and build the (hour, dow, month) → mean_load table."""
        df = pd.read_csv(csv_path, parse_dates=["utc_timestamp"])
        df["utc_timestamp"] = df["utc_timestamp"].dt.tz_localize(None)
        df["hour"] = df["utc_timestamp"].dt.hour
        df["dow"] = df["utc_timestamp"].dt.day_of_week   # 0=Mon, 6=Sun
        df["month"] = df["utc_timestamp"].dt.month
        df["load"] = df["DK_1_load_actual_entsoe_transparency"]
        df = df[df["load"].notna()].copy()

        if df.empty:
            raise ValueError(
                "The load CSV contains no valid (non-null) rows. "
                "Cannot build a forecast profile."
            )

        profile = (
            df.groupby(["hour", "dow", "month"])["load"]
            .mean()
            .reset_index()
            .rename(columns={"load": "mean_load"})
        )
        self._profile = profile.set_index(["hour", "dow", "month"])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def forecast(
        self,
        horizon_hours: int,
        start_hour: int = 0,
        start_dow: int = 0,
        start_month: int = 1,
    ) -> list[float]:
        """Return a list of *horizon_hours* forecasted demand values (MW).

        The forecast walks forward hour-by-hour from the provided start
        point, wrapping day-of-week and month as needed, and looks up the
        historical mean load for each *(hour, dow, month)* combination.

        Parameters
        ----------
        horizon_hours:
            Number of hours to forecast (≥ 1).
        start_hour:
            Hour-of-day at which the forecast begins (0–23).
        start_dow:
            Day of the week at which the forecast begins (0=Monday, 6=Sunday).
        start_month:
            Calendar month at which the forecast begins (1–12).

        Returns
        -------
        list[float]
            Forecasted demand in MW, one value per hour.

        Raises
        ------
        ValueError
            If any required *forecast* parameters are out of range.
        """
        if horizon_hours < 1:
            raise ValueError("horizon_hours must be at least 1.")
        if not (0 <= start_hour <= 23):
            raise ValueError("start_hour must be in [0, 23].")
        if not (0 <= start_dow <= 6):
            raise ValueError("start_dow must be in [0, 6].")
        if not (1 <= start_month <= 12):
            raise ValueError("start_month must be in [1, 12].")

        result: list[float] = []
        hour = start_hour
        dow = start_dow
        month = start_month
        days_elapsed = 0

        for _ in range(horizon_hours):
            mean_load = self._lookup(hour, dow, month)
            result.append(round(float(mean_load), 2))

            # Advance one hour
            hour += 1
            if hour == 24:
                hour = 0
                dow = (dow + 1) % _DAYS_IN_WEEK
                days_elapsed += 1
                # Advance month approximately every 30 days
                month = ((start_month - 1 + days_elapsed // 30) % _MONTHS_IN_YEAR) + 1

        return result

    # ------------------------------------------------------------------

    def _lookup(self, hour: int, dow: int, month: int) -> float:
        """Return mean load for *(hour, dow, month)*, with fallbacks."""
        key = (hour, dow, month)
        if key in self._profile.index:
            return float(self._profile.loc[key, "mean_load"])

        # Fallback 1: same hour and month, any day-of-week
        try:
            fallback = self._profile.loc[
                self._profile.index.get_level_values("hour") == hour
            ]
            fallback = fallback.loc[
                fallback.index.get_level_values("month") == month
            ]
            if not fallback.empty:
                return float(fallback["mean_load"].mean())
        except (KeyError, TypeError):
            pass

        # Fallback 2: global mean for this hour
        try:
            hour_rows = self._profile.loc[
                self._profile.index.get_level_values("hour") == hour
            ]
            if not hour_rows.empty:
                return float(hour_rows["mean_load"].mean())
        except (KeyError, TypeError):
            pass

        # Ultimate fallback: grand mean
        return float(self._profile["mean_load"].mean())
