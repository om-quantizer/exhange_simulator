# utils.py
# Utility functions for unique order ID generation and timestamping.

import itertools, time

_order_id_gen = itertools.count(1)
def get_next_order_id():
    """Return the next unique order ID."""
    return next(_order_id_gen)

def current_timestamp_ns():
    """Return the current time in nanoseconds."""
    return time.time_ns()

def enforce_tick(price):
    # First, round to the nearest multiple of 0.05, then force two decimals.
    return round(round(price / 0.05) * 0.05, 2)

