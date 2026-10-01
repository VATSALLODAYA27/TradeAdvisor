"""Offline checks for the settings-driven indicators and the rules round-trip."""
import pandas as pd

import data
from advisor import RULES, dump_rules, load_rules

up = pd.Series([100 + i for i in range(120)], dtype=float)
df = pd.DataFrame({"Open": up, "High": up + 1, "Low": up - 1, "Close": up, "Volume": 1000.0})
s = data.validate_settings({"ema": [9, 21], "sma": [50], "supertrend": [7, 2.5]})

ind = data.indicators(df, s)
assert ind["supertrend_dir"].iloc[-1] == 1 and ind["supertrend"].iloc[-1] < up.iloc[-1]  # uptrend: line below price
down = df[::-1].reset_index(drop=True)
assert data.indicators(down, s)["supertrend_dir"].iloc[-1] == -1
assert ind["rsi"].iloc[-1] > 90  # only up-moves
assert set(data.metric_names(s)["Daily"]) - {"close", "high_52w", "low_52w", "pct_from_52w_high", "ret_1m", "ret_3m"} == set(ind.columns)

for bad in [{"ema": [1]}, {"macd": [26, 12, 9]}, {"bollinger": [20, 0]}, {"orb_minutes": 7}, {"rsi": True}]:
    try:
        data.validate_settings(bad)
        raise AssertionError(f"accepted {bad}")
    except ValueError:
        pass

assert load_rules(dump_rules(RULES)) == RULES  # builder save -> TOML -> same rules
tricky = {"my advisor": {"default": "WAIT", "BUY NOW": [["rsi", "between", [30.5, 40]], ["close", ">", "ema_21"]]}}
assert load_rules(dump_rules(tricky)) == tricky
print("ok")
