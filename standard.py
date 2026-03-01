import pandas as pd
import numpy as np

pd.set_option("display.max_colwidth", None)
pd.set_option("display.max_columns", None)
pd.options.display.float_format = "{:,.3f}".format

rng = np.random.RandomState(24)
# rng = np.random   # optionally, use no pre-determined random seed
