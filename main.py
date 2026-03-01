from standard import *
from setup import Setup
from market import Market
from chart import chart

s = Setup()

a = [s.units(1, "nuclear", 500, 2000, i + 3, 0, 1000, 24, False, 0) for i in range(4)]

b = [s.units(1, "hydro", 0, 1000, i, 0, 1000, 0, False, 0) for i in range(2)]

a += b

s.setup_generator_bids(a)
m = Market(s.original_bids, s.load_schedule.iloc[: 24 * 7])
m.start()
chart(m.logs)
