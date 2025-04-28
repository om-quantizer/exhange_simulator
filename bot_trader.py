# bot_trader.py
# Module: BotTrader
# Description: Defines the BotTrader class which simulates autonomous trading agents (bots).
# Each bot updates its own private valuation (personal_price) via a Geometric Brownian Motion model,
# makes order decisions based on its TraderProfile, interacts with the MatchingEngine to place, edit,
# and cancel orders, and enforces risk constraints like position limits and circuit breakers.

import time                   # Provides time.perf_counter() and sleep functions for precise timing
import random                 # Supplies random number generators for stochastic behavior
import math                   # Provides exponential and square-root functions for GBM updates
import logging                # Used for logging bot-specific actions, state changes, and errors

import config                 # Imports global simulation parameters (e.g., price, durations, thresholds)
from utils import enforce_tick # Utility to snap floating prices to discrete tick increments
from trade_profile import PASSIVE, TraderProfile  # Default behavior profile and profile interface

class BotTrader:
    """
    BotTrader encapsulates the behavior of a single algorithmic trading bot.

    Attributes:
        bot_id (int): Unique identifier for this bot instance.
        engine (MatchingEngine): Reference to the shared matching engine for order processing.
        personal_price (float): Bot's internal valuation, evolves via GBM plus mean-reversion.
        mu (float): Drift parameter controlling average directional movement of personal_price.
        sigma (float): Volatility parameter controlling random fluctuations.
        profile (TraderProfile): Behavior settings (e.g., order frequency, aggression).
        last_known_ltp (float): Last Traded Price observed from market updates.
        position (int): Net position (long positive, short negative) held by the bot.
        log (Logger): Dedicated logger for this bot's actions.
        active_orders (dict[int, Order]): Live orders tracked by their order IDs.
        start_delay (float): Random delay before bot enters trading to avoid synchronization.
        trading_duration (float): Time window length within which the bot actively trades.
        start_time (float | None): Timestamp marking the beginning of trading activity.
    """
    def __init__(self, bot_id: int, engine, profile: TraderProfile = None, mu: float = 0.0, sigma: float = 0.001):
        # Basic identifiers and shared references
        self.bot_id = bot_id                              # Unique index for logging and tracking
        self.engine = engine                              # MatchingEngine for order routing

        # Initialize the private 'personal_price' around INITIAL_PRICE ±1 to create diversity
        self.personal_price = config.INITIAL_PRICE + random.uniform(-1.0, 1.0)
        self.mu = mu                                      # Mean trend of price updates
        self.sigma = sigma                                # Randomness magnitude in price updates

        # Assign behavior profile or default to PASSIVE if none provided
        self.profile = profile if profile is not None else PASSIVE

        # Market state observations and current holdings
        self.last_known_ltp = config.INITIAL_PRICE       # Initialize as starting price
        self.position = 0                                 # No holdings at initialization

        # Logger scoped to this bot for clear separation of logs
        self.log = logging.getLogger(f"bot_{bot_id}")
        self.active_orders = {}                           # OrderID -> Order object for lifecycle management

        # Randomize entry/exit times to simulate asynchronous participation
        self.start_delay = random.uniform(0, 0.3 * config.SEC_PER_DAY)
        self.trading_duration = random.uniform(0.5 * config.SEC_PER_DAY, config.SEC_PER_DAY)
        self.start_time = None                            # Will be set at run() invocation

    def update_personal_price(self) -> None:
        """
        Updates personal_price using a stochastic Geometric Brownian Motion (GBM) model
        combined with a small mean-reversion term drawing toward the last known market price.

        Steps:
            1. Sample Z ~ N(0,1) for random shock.
            2. Compute GBM: S_new = S_prev * exp((mu - 0.5*sigma^2)*dt + sigma*sqrt(dt)*Z).
            3. Apply a correction alpha*(last_known_ltp - S_new) for mean-reversion.
            4. Snap the result to the nearest configured tick size.
        """
        Z = random.normalvariate(0, 1)  # Standard normal variable
        effective_sigma = self.sigma * self.profile.price_sensitivity
        # GBM drift + diffusion component over one profile.tick_interval
        drift_term = (self.mu - 0.5 * effective_sigma**2) * self.profile.tick_interval
        diffusion_term = effective_sigma * math.sqrt(self.profile.tick_interval) * Z
        new_price = self.personal_price * math.exp(drift_term + diffusion_term)

        # Mean reversion: small pull toward observed market price
        alpha = 0.05
        new_price += alpha * (self.last_known_ltp - new_price)
        self.personal_price = enforce_tick(new_price)  # Enforce discrete price grid

    def run(self, duration: float = config.SEC_PER_DAY) -> None:
        """
        Main execution loop for the bot. Runs for up to `duration` seconds,
        performing: personal_price updates, dynamic profile switching, order decisions,
        risk checks, and random delays.

        Args:
            duration (float): Time allocated for this bot to trade (in seconds).
        """
        simulation_start = time.perf_counter()           # High precision start timestamp
        # Phase 1: Entry delay before trading begins
        while time.perf_counter() - simulation_start < self.start_delay:
            time.sleep(0.1)                              # Sleep in small increments to check again
        self.start_time = time.perf_counter()             # Timestamp when trading window starts
        trading_end = self.start_time + self.trading_duration

        # Prepare for dynamic profile updates at regular intervals
        last_profile_update = time.perf_counter()
        profile_update_interval = 120.0  # seconds

        # Phase 2: Active trading loop
        while time.perf_counter() < trading_end:
            # a) Market halt handling via circuit breaker
            if self.engine.circuit_active:
                # Cancel all active orders to comply with halt
                for oid in list(self.active_orders):
                    self.engine.order_book.cancel_order(oid)
                    del self.active_orders[oid]
                self.log.info("Circuit active: paused trading until reset.")
                time.sleep(1)
                continue

            # b) Update internal valuation
            self.update_personal_price()
            self.last_known_ltp = self.engine.last_traded_price or self.last_known_ltp

            # c) Optionally switch trading profile based on updated engine weights
            current_time = time.perf_counter()
            if current_time - last_profile_update >= profile_update_interval:
                # Create perturbed weights for selection
                dyn_weights = [max(0, w + random.uniform(-0.05, 0.05)) for w in self.engine.base_weights]
                total = sum(dyn_weights) or 1
                normalized = [w/total for w in dyn_weights]
                old = self.profile.name
                # Randomly choose among engine.profiles with new weights
                self.profile = random.choices(self.engine.profiles, weights=normalized, k=1)[0]
                last_profile_update = current_time
                self.log.info(f"Profile switch: {old} -> {self.profile.name}")

            # d) Market data queries
            best_bid, bid_qty = self.engine.order_book.get_best_bid()
            best_ask, ask_qty = self.engine.order_book.get_best_ask()
            market_price = self.engine.order_book.get_market_price()

            # e) Trend and volatility signals
            trend = self.engine.update_trend_indicator(self.engine.last_traded_price)
            relative_vol = abs(self.personal_price - self.last_known_ltp) / max(self.last_known_ltp, 1)

            # f) Determine trade side: buy or sell
            if relative_vol > config.VOLATILITY_THRESHOLD:
                # In high volatility, follow clear trend if present
                if trend in ("bullish", "bearish"):
                    side = "B" if trend == "bullish" else "S"
                else:
                    # Fallback: buy if internal > market
                    side = "B" if self.personal_price > self.last_known_ltp else "S"
            else:
                # Use profile-specific logic for side selection
                if self.profile.name == "Momentum Trader":
                    side = ("B" if trend == "bullish" else "S" if trend == "bearish"
                            else random.choice(["B", "S"]))
                elif self.profile.name.startswith("Contrarian"):
                    # Contrarians trade against trend
                    if trend == "bullish": side = ("S" if "Seller" in self.profile.name else "B")
                    elif trend == "bearish": side = ("B" if "Buyer" in self.profile.name else "S")
                    else: side = "B" if self.personal_price > self.last_known_ltp else "S"
                else:
                    # Passive or others: compare valuations
                    side = "B" if self.personal_price > self.last_known_ltp else "S"

            # g) Compute limit price via profile’s pricing function
            limit_price = self.profile.compute_order_price(
                bot=self,
                side=side,
                best_bid_price=best_bid,
                best_ask_price=best_ask
            )

            # h) Determine order quantity based on time-of-day volume profile
            base_qty = random.randint(config.MIN_ORDER_QTY, config.MAX_ORDER_QTY)
            elapsed = time.perf_counter() - self.start_time
            frac = elapsed / self.trading_duration
            # Volume peaks at start and end of day via quadratic curve
            vol_factor = 1 + config.VOLUME_PEAK_FACTOR * (4 * (frac - 0.5)**2)
            qty = max(1, int(base_qty * self.profile.volume_multiplier * vol_factor))

            # i) Enforce risk limits: no orders breaching position limits
            if (side == "B" and self.position + qty > config.POSITION_LIMIT) or \
               (side == "S" and self.position - qty < -config.POSITION_LIMIT):
                self.log.debug(f"Risk limit: skip {side}{qty} at {limit_price}")
                time.sleep(0.5); continue

            # j) Decide action type: new, edit, or cancel
            action = random.choices(
                ["new", "edit", "cancel"],
                weights=[self.profile.order_frequency, 0.5, self.profile.cancellation_rate],
                k=1
            )[0]

            if action == "new":
                # Submit new limit order
                order = self.engine.process_order(side, limit_price, qty, owner=None)
                if order:
                    self.active_orders[order.id] = order
                    self.log.info(f"N: Placed new order {order.id} (Fair={limit_price:.2f}, Mkt={market_price:.2f}) using {self.profile.name}")
                else:
                    self.log.info(f"N: Order fully executed on placement (Fair={limit_price:.2f}, Mkt={market_price:.2f}) using {self.profile.name}")

            elif action == "edit" and self.active_orders:
                # Randomly pick one active order to modify
                oid = random.choice(list(self.active_orders.keys()))
                ord_obj = self.active_orders[oid]
                if ord_obj.active:
                    new_p = enforce_tick(ord_obj.price + random.uniform(-0.01, 0.01))
                    new_q = max(1, ord_obj.quantity + random.randint(-1, 1))
                    if self.engine.order_book.edit_order(oid, new_price=new_p, new_quantity=new_q):
                        self.log.info(f"M: Edited order {oid}: ->{new_q}@{new_p}")
                    else:
                        self.log.warning(f"EDIT fail for {oid}")

            elif action == "cancel" and self.active_orders:
                # Cancel a random outstanding order
                oid = random.choice(list(self.active_orders.keys()))
                if self.engine.order_book.cancel_order(oid):
                    self.log.info(f"X: Cancelled order {oid}")
                    del self.active_orders[oid]
                else:
                    self.log.warning(f"CANCEL fail for {oid}")

            # k) Compute next sleep interval adapting to profile speed and market activity
            eff_freq = self.profile.order_frequency * (1.5 if relative_vol>config.VOLATILITY_THRESHOLD else 1)
            base_int = config.TICK_INTERVAL / eff_freq
            reaction_int = base_int * self.profile.reaction_speed
            phase = 1 + config.VOLUME_PEAK_FACTOR * (4 * (frac - 0.5)**2)
            sleep_dt = random.uniform(reaction_int, reaction_int * 1.5 * phase)
            time.sleep(sleep_dt)

        # # End of run loop: log exit and final position
        # self.log.info(f"Trading done: position={self.position}, active_orders={len(self.active_orders)}")



# import time, random, math, logging
# import config
# from utils import enforce_tick
# from trade_profile import PASSIVE, TraderProfile

# class BotTrader:
#     def __init__(self, bot_id, engine, profile: TraderProfile = None, mu=0.0, sigma=0.001):
#         self.bot_id = bot_id
#         self.engine = engine
#         self.personal_price = config.INITIAL_PRICE + random.uniform(-1.0, 1.0)
#         self.mu = mu
#         self.sigma = sigma
#         self.profile = profile if profile is not None else PASSIVE
#         self.last_known_ltp = config.INITIAL_PRICE
#         self.position = 0
#         self.log = logging.getLogger(f"bot_{bot_id}")
#         self.active_orders = {}
#         self.trade_count = 0  # cumulative trade count

#         # Portfolio initialization based on profile
#         self.cash = random.uniform(*self.profile.cash_range)
#         self.shares = random.randint(*self.profile.share_range)
#         self.debt = 0.0
#         self.max_leverage = config.MAX_LEVERAGE

#         # store profile duration fraction for each run
#         self._profile_duration_fraction = self.profile.trading_duration_fraction

#         # random start delay
#         self.start_delay = random.uniform(0, 0.3 * config.SEC_PER_DAY)
#         self.start_time = None

#     def update_personal_price(self):
#         Z = random.normalvariate(0, 1)
#         effective_sigma = self.sigma * self.profile.price_sensitivity
#         effective_mu = self.mu + config.GLOBAL_DRIFT
        
#         new_price = self.personal_price * math.exp(
#             (effective_mu - 0.5 * effective_sigma**2) * self.profile.tick_interval +
#             effective_sigma * math.sqrt(self.profile.tick_interval) * Z
#         )
        
#         alpha = 0.05
#         new_price += alpha * (self.last_known_ltp - new_price)
#         self.personal_price = enforce_tick(new_price)

#     def update_risk_profile(self):
#         # if cash low, become more conservative
#         if self.cash < 0.5 * config.INITIAL_CAPITAL:
#             self.profile.order_frequency = max(0.1, self.profile.order_frequency * 0.8)
#             self.profile.cancellation_rate = min(1.0, self.profile.cancellation_rate + 0.1)
#             self.profile.aggression *= 0.8
#             self.log.info("Risk profile adjusted due to low cash.")

#     def run(self, duration=config.SEC_PER_DAY):
#         """
#         Run trading for a window equal to duration * profile_duration_fraction.
#         """
#         simulation_start = time.perf_counter()
#         # wait for start delay
#         while time.perf_counter() - simulation_start < self.start_delay:
#             time.sleep(1)
#         self.start_time = time.perf_counter()
#         trading_end_time = self.start_time + duration * self._profile_duration_fraction

#         last_profile_update = time.perf_counter()
#         update_interval = 120  # seconds

#         while True:
#             now = time.perf_counter()
#             remaining_time = trading_end_time - now
#             if remaining_time <= 0:
#                 self.log.info("Trading period over for this bot.")
#                 break

#             if self.engine.circuit_active:
#                 for order_id in list(self.active_orders.keys()):
#                     self.engine.order_book.cancel_order(order_id)
#                     del self.active_orders[order_id]
#                 self.log.info("Market halted due to shock. Pausing trading.")
#                 time.sleep(5)
#                 continue

#             self.update_risk_profile()
#             self.update_personal_price()
#             if self.engine.last_traded_price is not None:
#                 self.last_known_ltp = self.engine.last_traded_price

#             # dynamic profile update
#             if now - last_profile_update >= update_interval:
#                 dynamic_weights = [max(0, w + random.uniform(-0.05, 0.05)) for w in self.engine.base_weights]
#                 total = sum(dynamic_weights)
#                 normalized = [w/total for w in dynamic_weights]
#                 old = self.profile.name
#                 self.profile = random.choices(self.engine.profiles, weights=normalized, k=1)[0]
#                 last_profile_update = now
#                 self.log.info(f"Dynamic profile update: Changed from {old} to {self.profile.name}")

#             # market data
#             best_bid_price, bid_volume = self.engine.order_book.get_best_bid()
#             best_ask_price, ask_volume = self.engine.order_book.get_best_ask()
#             current_market = self.engine.order_book.get_market_price()

#             trend = self.engine.update_trend_indicator(self.engine.last_traded_price)
#             volatility = abs(self.personal_price - self.last_known_ltp) / self.last_known_ltp

#             # decide side
#             if volatility > config.VOLATILITY_THRESHOLD:
#                 if trend in ["bullish", "bearish"]:
#                     side = "B" if trend == "bullish" else "S"
#                 else:
#                     side = "B" if self.personal_price > self.last_known_ltp else "S"
#             else:
#                 if self.profile.name == "Momentum Trader":
#                     side = "B" if trend == "bullish" else "S" if trend == "bearish" else random.choice(["B","S"])
#                 elif self.profile.name in ["Contrarian Buyer", "Contrarian Seller"]:
#                     if trend == "bullish" and self.profile.name == "Contrarian Seller": side = "S"
#                     elif trend == "bearish" and self.profile.name == "Contrarian Buyer": side = "B"
#                     else: side = "B" if self.personal_price > self.last_known_ltp else "S"
#                 else:
#                     diff = self.personal_price - self.last_known_ltp
#                     side = "S" if diff < 0 else "B"

#             order_price = self.profile.compute_order_price(
#                 bot=self, side=side,
#                 best_bid_price=best_bid_price, best_ask_price=best_ask_price
#             )

#             # portfolio constraints
#             if side == "B":
#                 max_qty = int(self.cash * (self.max_leverage if config.LEVERAGE_ALLOWED else 1.0) / order_price) if order_price>0 else 0
#                 if max_qty < config.MIN_ORDER_QTY:
#                     self.log.info(f"Skipping BUY: insufficient cash ({self.cash:.2f}).")
#                     time.sleep(1)
#                     continue
#             else:
#                 if self.shares < config.MIN_ORDER_QTY:
#                     self.log.info(f"Skipping SELL: insufficient shares ({self.shares}).")
#                     time.sleep(1)
#                     continue

#             base_qty = random.randint(config.MIN_ORDER_QTY, config.MAX_ORDER_QTY)
#             t_frac = (now - self.start_time) / (duration * self._profile_duration_fraction)
#             volume_weight = 1 + config.VOLUME_PEAK_FACTOR * (4*(t_frac-0.5)**2)
#             qty = (max(1, min(base_qty, max_qty)) if side=="B" else max(1, min(base_qty, self.shares)))
#             qty = int(qty * self.profile.volume_multiplier * volume_weight)

#             self.log.info(f"Market Info: LTP={self.engine.last_traded_price:.2f}, BestBidVol={bid_volume}, BestAskVol={ask_volume}")

#             action = random.choices(["new","edit","cancel"],
#                                      weights=[self.profile.order_frequency, 0.5, self.profile.cancellation_rate],
#                                      k=1)[0]

#             if action == "new":
#                 order = self.engine.process_order(side, order_price, qty, owner=self)
#                 if order:
#                     self.active_orders[order.id] = order
#                     self.log.info(f"N: Placed new order {order} (Fair={order_price:.2f}, Mkt={current_market:.2f}) using {self.profile.name}")
#                 else:
#                     self.log.info(f"N: Order fully executed on placement (Fair={order_price:.2f}, Mkt={current_market:.2f}) using {self.profile.name}")
#             elif action == "edit" and self.active_orders:
#                 oid = random.choice(list(self.active_orders.keys()))
#                 order = self.active_orders[oid]
#                 if order.active:
#                     new_price = enforce_tick(order.price + random.uniform(-0.01,0.01))
#                     new_qty = max(1, order.quantity + random.randint(-1,1))
#                     success = self.engine.order_book.edit_order(oid, new_price=new_price, new_quantity=new_qty)
#                     if success: self.log.info(f"M: Edited order {oid} to {new_price:.2f} @ {new_qty}")
#                     else: self.log.info(f"M: Failed to edit order {oid}")
#             elif action == "cancel" and self.active_orders:
#                 oid = random.choice(list(self.active_orders.keys()))
#                 order = self.active_orders[oid]
#                 if order.active:
#                     success = self.engine.order_book.cancel_order(oid)
#                     if success:
#                         self.log.info(f"X: Cancelled order {oid}")
#                         del self.active_orders[oid]
#                     else:
#                         self.log.info(f"X: Failed to cancel order {oid}")

#             # compute sleep
#             eff_freq = self.profile.order_frequency * (1.5 if volatility>config.VOLATILITY_THRESHOLD else 1.0)
#             base_int = config.TICK_INTERVAL / eff_freq
#             react_int = base_int * self.profile.reaction_speed
#             phase = 1 + config.VOLUME_PEAK_FACTOR * (4*(t_frac-0.5)**2)
#             sleep_t = random.uniform(react_int, 1.5*react_int*phase)
#             sleep_t = min(sleep_t, remaining_time)
#             time.sleep(sleep_t)
