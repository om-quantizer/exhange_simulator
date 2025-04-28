# utils.py
# Utility functions supporting the exchange simulation:
# - Unique order ID generation
# - High-resolution timestamping
# - Enforcing tick size
# - Circuit breaker activation and reset

import itertools    # For creating the unique ID counter
import time         # For timestamps
import threading    # For scheduling circuit reset
import config       # For access to CIRCUIT_BREAKER_DURATION

# Generator for order IDs: starts at 1 and increments by 1
_order_id_gen = itertools.count(1)

def get_next_order_id():
    """
    Return the next unique order ID.
    Uses a global counter to ensure no collisions.
    """
    return next(_order_id_gen)

def current_timestamp_ns():
    """
    Return the current time in nanoseconds.
    Provides high-resolution timestamps for order sequencing.
    """
    return time.time_ns()

def enforce_tick(price):
    """
    Align a floating-point price to the nearest valid tick:
    - First divide by 0.05 (tick size), round to nearest integer,
      then multiply back and round to two decimal places.
    Ensures all prices adhere to exchange tick rules.
    """
    # Round to multiple of 0.05, then format to 2 decimal places
    return round(round(price / 0.05) * 0.05, 2)

def trigger_circuit_breaker(engine):
    """
    Activate the circuit breaker on the MatchingEngine:
    - Sets circuit_active = True and records trigger time.
    - Schedules reset_circuit_breaker() after CIRCUIT_BREAKER_DURATION seconds.
    """
    engine.circuit_active = True
    engine.circuit_trigger_time = time.perf_counter()
    # Use a timer thread to call reset after configured duration
    timer = threading.Timer(config.CIRCUIT_BREAKER_DURATION, reset_circuit_breaker, args=(engine,))
    timer.start()

def reset_circuit_breaker(engine):
    """
    Reset the circuit breaker flag on the MatchingEngine:
    - Clears circuit_active and trigger time.
    Called automatically by the timer set in trigger_circuit_breaker().
    """
    engine.circuit_active = False
    engine.circuit_trigger_time = None
