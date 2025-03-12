# market_data.py
# Simulate continuous market price ticks using Geometric Brownian Motion (GBM)
# with high-resolution timing.
import math, random, time
import logging
from utils import enforce_tick
import config

class MarketData:
    """Generates tick-by-tick prices using GBM with high-resolution time."""
    def __init__(self, initial_price, drift, volatility, interval):
        self.price = enforce_tick(initial_price)
        self.mu = drift
        self.sigma = volatility
        # dt is in seconds; for microtime you may set dt to a very small value (e.g. 0.0001)
        self.dt = interval  
        self.running = False
        self.log = logging.getLogger("exchange")
    
    def step(self):
        """Calculate the next price tick using the GBM formula."""
        Z = random.normalvariate(0, 1)
        new_price = self.price * math.exp((self.mu - 0.5 * self.sigma**2) * self.dt +
                                          self.sigma * (self.dt**0.5) * Z)
        self.price = enforce_tick(new_price)

        # Log the tick with high-resolution time if needed.
        self.log.info(f"MarketData Tick: Price = {self.price:.2f}")
        return self.price

    def run(self, duration=60):
        """
        Generate price ticks continuously for the given duration (in seconds)
        using a high-resolution timer.
        """
        self.running = True
        start_ns = time.perf_counter_ns()
        duration_ns = duration * 1_000_000_000  # convert seconds to nanoseconds
        next_tick_ns = start_ns
        while self.running and (time.perf_counter_ns() - start_ns < duration_ns):
            now_ns = time.perf_counter_ns()
            if now_ns >= next_tick_ns:
                self.step()
                # Schedule next tick; dt is in seconds.
                next_tick_ns += int(self.dt * 1_000_000_000)
            else:
                # Sleep a very short time to yield control.
                time.sleep(0.00001)
        self.running = False

    def get_price(self):
        """Return the current price."""
        return self.price
