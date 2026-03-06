"""Stochastic weather factor generation using Gaussian-smoothed random noise."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
from scipy.ndimage import gaussian_filter1d


class Weather:
    """Generates weather-factor schedules for renewable output adjustment.

    Parameters
    ----------
    profile:
        Three-element list ``[min_factor, max_factor, smoothing_factor]``.
    seed:
        Random seed for reproducibility.  ``None`` for non-deterministic.
    """

    def __init__(self, profile: list[float], seed: int | None = 24) -> None:
        self.profile = profile
        self.weather_factor_schedules: list[npt.NDArray[np.floating]] = []
        self._rng = np.random.RandomState(seed=seed)

    def create_schedules(self, n_schedule: int, continuous: bool = False) -> None:
        """Populate ``self.weather_factor_schedules`` with *n_schedule* arrays."""
        if continuous:
            self.weather_factor_schedules = self._smooth_random_curve(
                self.profile, n_schedule, True
            )
        else:
            self.weather_factor_schedules = []
            for _ in range(n_schedule):
                self.weather_factor_schedules.append(
                    self._smooth_random_curve(self.profile, n_schedule, False)
                )

    def _smooth_random_curve(
        self,
        profile: list[float],
        n_schedule: int,
        continuous: bool,
    ) -> npt.NDArray[np.floating] | list[npt.NDArray[np.floating]]:
        min_val, max_val, smoothing_factor = profile
        val_range = max_val - min_val

        # Create random noise
        if continuous:
            x = self._rng.random(24 * n_schedule)
        else:
            x = self._rng.random(24)

        # Smoothing
        x_smooth = gaussian_filter1d(x, smoothing_factor, mode="nearest")

        # Normalisation
        x_smooth -= x_smooth.min()
        if x_smooth.max() > 0:
            x_smooth /= x_smooth.max()

        result: npt.NDArray = min_val + x_smooth * val_range

        if continuous:
            parts = list(np.split(result, n_schedule))
            return parts
        else:
            return result
