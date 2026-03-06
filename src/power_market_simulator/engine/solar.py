"""Solar power producer with cosine² generation profile."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt


class SolarPowerProducer:
    """Models a solar generator using a cosine-squared daily output curve.

    Parameters
    ----------
    nameplate_capacity:
        Peak power output (MW) at full sunlight.
    sunlight_schedule:
        Three-element list ``[sunrise_hour, peak_hour, sunset_hour]``.
    """

    def __init__(
        self,
        nameplate_capacity: float = 0.0,
        sunlight_schedule: list[int] | None = None,
    ) -> None:
        self.sunlight_schedule = sunlight_schedule or [6, 12, 18]
        self.nameplate_capacity = nameplate_capacity
        self.supply_schedules: list[npt.NDArray[np.floating]] = []
        self.original: list[npt.NDArray[np.floating]] = []

    def create_supply_schedules(self, n_schedule: int) -> None:
        """Generate *n_schedule* identical clear-sky daily output curves."""
        sunrise, peak, sunset = self.sunlight_schedule
        capacity = self.nameplate_capacity
        self.supply_schedules = []

        for _ in range(n_schedule):
            hours = np.arange(24)
            output = np.zeros(24)
            mask = (hours >= sunrise) & (hours <= sunset)
            h = hours[mask]
            x = (h - peak) / (sunset - sunrise) * np.pi
            y = np.cos(x) ** 2
            output[mask] = capacity * y
            self.supply_schedules.append(output)

    def apply_weather_factor(
        self, weather_factor_schedules: list[npt.NDArray[np.floating]]
    ) -> None:
        """Multiply supply schedules by stochastic weather factors.

        Saves the original clear-sky schedules in ``self.original``.
        """
        if len(weather_factor_schedules) != len(self.supply_schedules):
            raise ValueError(
                f"Weather schedule count ({len(weather_factor_schedules)}) "
                f"does not match supply schedule count ({len(self.supply_schedules)})"
            )

        weather_arr = np.stack(weather_factor_schedules)
        supply_arr = np.stack(self.supply_schedules)
        adjusted = weather_arr * supply_arr

        self.original = list(self.supply_schedules)
        self.supply_schedules = list(adjusted)
