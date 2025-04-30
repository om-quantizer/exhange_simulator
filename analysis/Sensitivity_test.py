import itertools
import re
import pandas as pd
import numpy as np
import config
from order_book        import OrderBook
from matching_engine   import MatchingEngine
from analysis.main              import run_simulation_day
from trade_profile     import MOMENTUM_TRADER

# ───── USER CONFIG ───────────────────────────────────────────────────────────
param_grid = {
    "mu":                    [0.0000001, 0.00001, 0.001],
    "sigma":                 [0.0001, 0.0005, 0.001],
    "num_bots":              [50, 500, 5000],
    "volatility_threshold":  [0.0005, 0.001, 0.002],
}

intervals = {
    "5s":  "5S",
    "20s":  "20S",
    # "1min": "1min",
    # "5min": "5min",
    # "15min": "15min",
}

# ───── LOG–PARSING UTILS ─────────────────────────────────────────────────────
TRADE_LINE_REGEX = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+).*"
    r"T: Trade executed:.*?LTP=(?P<ltp>\d+\.\d+)"
)

def parse_trade_log(path="logs/exchange.log"):
    """
    Reads the exchange.log, extracts all 'T: Trade executed… LTP=…' lines,
    and returns a DataFrame indexed by timestamp with a 'price' column.
    """
    records = []
    with open(path, "r") as f:
        for line in f:
            m = TRADE_LINE_REGEX.match(line)
            if not m:
                continue
            ts = pd.to_datetime(m.group("ts"))
            price = float(m.group("ltp"))
            records.append((ts, price))
    if not records:
        return pd.DataFrame(columns=["price"])
    df = pd.DataFrame(records, columns=["timestamp", "price"]).set_index("timestamp")
    return df

def compute_metrics(df_ticks, intervals):
    results = {}
    for label, rule in intervals.items():
        agg = df_ticks["price"].resample(rule).last().dropna()
        lr  = np.log(agg).diff().dropna()
        results[f"{label}_vol"]   = np.sqrt((lr**2).sum())
        results[f"{label}_skew"]  = lr.skew()
        results[f"{label}_kurt"]  = lr.kurtosis()
        results[f"{label}_n"]     = len(agg)
    return results

def run_one_day_return_ticks(mu, sigma, num_bots, vol_thresh):
    # --- 1) update parameters ---
    config.GBM_DRIFT_RANGE      = (mu, mu)
    config.GBM_VOLATILITY_RANGE = (sigma, sigma)
    config.NUM_BOTS             = num_bots
    config.VOLATILITY_THRESHOLD = vol_thresh

    # --- 2) clear out old logs so each run is isolated ---
    open("logs/exchange.log", "w").close()

    # --- 3) run the sim (it will re‐write logs/exchange.log) ---
    ob     = OrderBook()
    engine = MatchingEngine(ob)
    run_simulation_day(engine, day_index=1, open_price=config.INITIAL_PRICE)

    # --- 4) parse the fresh log for ticks ---
    df_ticks = parse_trade_log("logs/exchange.log")
    return df_ticks

# ───── RUN THE SWEEP ─────────────────────────────────────────────────────────
records = []
for combo in itertools.product(*(param_grid.values())):
    mu, sigma, num_bots, vt = combo
    df_ticks = run_one_day_return_ticks(mu, sigma, num_bots, vt)
    metrics  = compute_metrics(df_ticks, intervals)
    record   = dict(zip(param_grid.keys(), combo))
    record.update(metrics)
    records.append(record)

results_df = pd.DataFrame(records)
print("Sensitivity Analysis Results:")
print(results_df)
results_df.to_csv("sensitivity_results.csv", index=False)
