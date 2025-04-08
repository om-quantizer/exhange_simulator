# utils.py
# Utility functions for unique order ID generation and timestamping.

import itertools, time
import threading
import config

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

def trigger_circuit_breaker(engine):
    """
    Activates the circuit breaker and schedules its reset after the configured duration.
    """
    engine.circuit_active = True
    engine.circuit_trigger_time = time.perf_counter()
    # Use threading.Timer to ensure the breaker resets exactly after the duration.
    timer = threading.Timer(config.CIRCUIT_BREAKER_DURATION, reset_circuit_breaker, args=(engine,))
    timer.start()

def reset_circuit_breaker(engine):
    """
    Resets the circuit breaker flag.
    """
    engine.circuit_active = False
    engine.circuit_trigger_time = None