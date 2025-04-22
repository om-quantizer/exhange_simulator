# # # bot_trader.py
# # import time, random, math, logging
# # import config
# # from utils import enforce_tick
# # from trade_profile import PASSIVE, TraderProfile

# # class BotTrader:
# #     def __init__(self, bot_id, engine, profile: TraderProfile = None, mu=0.0, sigma=0.001):
# #         self.bot_id = bot_id
# #         self.engine = engine
# #         self.personal_price = config.INITIAL_PRICE + random.uniform(-1.0, 1.0)
# #         self.mu = mu
# #         self.sigma = sigma
# #         self.profile = profile if profile is not None else PASSIVE
# #         self.last_known_ltp = config.INITIAL_PRICE
# #         self.position = 0  
# #         self.log = logging.getLogger(f"bot_{bot_id}")
# #         self.active_orders = {}

# #     def update_personal_price(self):
# #         Z = random.normalvariate(0, 1)
# #         effective_sigma = self.sigma * self.profile.price_sensitivity
# #         new_price = self.personal_price * math.exp(
# #             (self.mu - 0.5 * effective_sigma**2) * self.profile.tick_interval +
# #             effective_sigma * math.sqrt(self.profile.tick_interval) * Z
# #         )
# #         alpha = 0.05
# #         new_price += alpha * (self.last_known_ltp - new_price)
# #         self.personal_price = enforce_tick(new_price)

# #     def run(self, duration=30):

# #         start_time = time.perf_counter()
# #         last_profile_update = start_time  # record the last time the profile was updated
# #         update_interval = 120  # seconds between dynamic profile updates

# #         while (time.perf_counter() - start_time) < duration:
# #             # If circuit breaker active, cancel orders and pause
# #             if self.engine.circuit_active:
# #                 for order_id in list(self.active_orders.keys()):
# #                     self.engine.order_book.cancel_order(order_id)
# #                     del self.active_orders[order_id]
# #                 self.log.info("Market halted due to shock. Pausing trading.")
# #                 time.sleep(5)
# #                 continue

# #             self.update_personal_price()

# #             if self.engine.last_traded_price is not None:
# #                 self.last_known_ltp = self.engine.last_traded_price


# #             # Dynamic profile update during the day:
# #             current_time = time.perf_counter()
# #             if current_time - last_profile_update >= update_interval:
# #                 # Generate new dynamic weights by perturbing the base weights stored in the engine.
# #                 dynamic_weights = [max(0, w + random.uniform(-0.05, 0.05)) for w in self.engine.base_weights]
# #                 total = sum(dynamic_weights)
# #                 normalized_weights = [w / total for w in dynamic_weights]
# #                 old_profile = self.profile.name
# #                 # Reassign profile using the updated weights.
# #                 self.profile = random.choices(self.engine.profiles, weights=normalized_weights, k=1)[0]
# #                 last_profile_update = current_time
# #                 self.log.info(f"Dynamic profile update: Changed from {old_profile} to {self.profile.name}")


# #             best_bid_price, _ = self.engine.order_book.get_best_bid()
# #             best_ask_price, _ = self.engine.order_book.get_best_ask()
# #             current_market = self.engine.order_book.get_market_price()

# #             # Determine trading side based on profile and market trend
# #             if self.profile.name == "Momentum Trader":
# #                 trend = self.engine.update_trend_indicator(self.engine.last_traded_price)
# #                 side = "B" if trend == "bullish" else "S" if trend == "bearish" else ("B" if random.random() < 0.5 else "S")
            
# #             elif self.profile.name in ["Contrarian Buyer", "Contrarian Seller"]:
# #                 trend = self.engine.update_trend_indicator(self.engine.last_traded_price)
# #                 if trend == "bullish" and self.profile.name == "Contrarian Seller":
# #                     side = "S"
# #                 elif trend == "bearish" and self.profile.name == "Contrarian Buyer":
# #                     side = "B"
# #                 else:
# #                     side = "B" if self.personal_price > self.last_known_ltp else "S"
                    
# #             else:
# #                 diff = self.personal_price - self.last_known_ltp
# #                 side = "S" if diff < 0 else "B"

# #             order_price = self.profile.compute_order_price(
# #                 bot=self,
# #                 side=side,
# #                 best_bid_price=best_bid_price,
# #                 best_ask_price=best_ask_price
# #             )

# #             base_qty = random.randint(config.MIN_ORDER_QTY, config.MAX_ORDER_QTY)
# #             t_fraction = (time.perf_counter() - start_time) / duration
# #             volume_weight = 1 + config.VOLUME_PEAK_FACTOR * (1 - 4 * (t_fraction - 0.5)**2)
# #             quantity = max(1, int(base_qty * self.profile.volume_multiplier * volume_weight))

# #             action = random.choices(
# #                 ["new", "edit", "cancel"],
# #                 weights=[self.profile.order_frequency, 0.5, self.profile.cancellation_rate],
# #                 k=1
# #             )[0]

# #             if action == "new":
# #                 order = self.engine.process_order(side, order_price, quantity, owner=None)
# #                 if order:
# #                     self.active_orders[order.id] = order
# #                     self.log.info(f"N: Placed new order {order} (Fair={order_price:.2f}, Mkt={current_market:.2f}) using {self.profile.name}")
# #                 else:
# #                     self.log.info(f"N: Order fully executed on placement (Fair={order_price:.2f}, Mkt={current_market:.2f}) using {self.profile.name}")
# #             elif action == "edit" and self.active_orders:
# #                 order_id = random.choice(list(self.active_orders.keys()))
# #                 order = self.active_orders[order_id]
# #                 if order.active:
# #                     new_offset = random.uniform(-0.01, 0.01)
# #                     new_price = enforce_tick(order.price + new_offset)
# #                     new_quantity = max(1, order.quantity + random.randint(-1, 1))
# #                     success = self.engine.order_book.edit_order(order_id, new_price=new_price, new_quantity=new_quantity)
# #                     if success:
# #                         self.log.info(f"M: Edited order {order_id} to {new_price:.2f} @ {new_quantity}")
# #                     else:
# #                         self.log.info(f"M: Failed to edit order {order_id}")
# #             elif action == "cancel" and self.active_orders:
# #                 order_id = random.choice(list(self.active_orders.keys()))
# #                 order = self.active_orders[order_id]
# #                 if order.active:
# #                     success = self.engine.order_book.cancel_order(order_id)
# #                     if success:
# #                         self.log.info(f"X: Cancelled order {order_id}")
# #                         del self.active_orders[order_id]
# #                     else:
# #                         self.log.info(f"X: Failed to cancel order {order_id}")

            
# #             min_interval = config.TICK_INTERVAL * (1/self.profile.order_frequency)

# #             sleep_time = random.uniform(min_interval, 1.5 * min_interval)
# #             time.sleep(sleep_time)


import time, random, math, logging
import config
from utils import enforce_tick
from trade_profile import PASSIVE, TraderProfile

class BotTrader:
    def __init__(self, bot_id, engine, profile: TraderProfile = None, mu=0.0, sigma=0.001):
        self.bot_id = bot_id
        self.engine = engine
        self.personal_price = config.INITIAL_PRICE + random.uniform(-1.0, 1.0)
        self.mu = mu
        self.sigma = sigma
        self.profile = profile if profile is not None else PASSIVE
        self.last_known_ltp = config.INITIAL_PRICE
        self.position = 0  
        self.log = logging.getLogger(f"bot_{bot_id}")
        self.active_orders = {}
        
        # Variable entry/exit: random start delay and dynamic trading duration.
        self.start_delay = random.uniform(0, 0.3 * config.SEC_PER_DAY)
        self.trading_duration = random.uniform(0.5 * config.SEC_PER_DAY, config.SEC_PER_DAY)
        self.start_time = None  # To be set when trading begins.

    def update_personal_price(self):
        Z = random.normalvariate(0, 1)
        effective_sigma = self.sigma * self.profile.price_sensitivity
        new_price = self.personal_price * math.exp(
            (self.mu - 0.5 * effective_sigma**2) * self.profile.tick_interval +
            effective_sigma * math.sqrt(self.profile.tick_interval) * Z
        )
        alpha = 0.05
        new_price += alpha * (self.last_known_ltp - new_price)
        self.personal_price = enforce_tick(new_price)

    def run(self, duration=30):
        simulation_start = time.perf_counter()
        # Wait until bot's start delay elapses.
        while time.perf_counter() - simulation_start < self.start_delay:
            time.sleep(1)
        self.start_time = time.perf_counter()
        trading_end_time = self.start_time + self.trading_duration

        last_profile_update = time.perf_counter()
        update_interval = 120  # seconds between dynamic profile updates

        while time.perf_counter() < trading_end_time:
            # Check circuit breaker.
            if self.engine.circuit_active:
                for order_id in list(self.active_orders.keys()):
                    self.engine.order_book.cancel_order(order_id)
                    del self.active_orders[order_id]
                self.log.info("Market halted due to shock. Pausing trading.")
                time.sleep(5)
                continue

            self.update_personal_price()
            if self.engine.last_traded_price is not None:
                self.last_known_ltp = self.engine.last_traded_price

            # Dynamic profile update.
            current_time = time.perf_counter()
            if current_time - last_profile_update >= update_interval:
                dynamic_weights = [max(0, w + random.uniform(-0.05, 0.05)) for w in self.engine.base_weights]
                total = sum(dynamic_weights)
                normalized_weights = [w / total for w in dynamic_weights]
                old_profile = self.profile.name
                self.profile = random.choices(self.engine.profiles, weights=normalized_weights, k=1)[0]
                last_profile_update = current_time
                self.log.info(f"Dynamic profile update: Changed from {old_profile} to {self.profile.name}")

            # Exit if trading window is over.
            if time.perf_counter() >= trading_end_time:
                self.log.info("Trading period over for this bot.")
                break

            best_bid_price, bid_volume = self.engine.order_book.get_best_bid()
            best_ask_price, ask_volume = self.engine.order_book.get_best_ask()
            current_market = self.engine.order_book.get_market_price()

            # Determine market trend and volatility.
            trend = self.engine.update_trend_indicator(self.engine.last_traded_price)
            volatility = abs(self.personal_price - self.last_known_ltp) / self.last_known_ltp

            # Decide order side – all profiles now use trend if volatility is high.
            if volatility > config.VOLATILITY_THRESHOLD:
                if trend in ["bullish", "bearish"]:
                    side = "B" if trend == "bullish" else "S"
                else:
                    side = "B" if self.personal_price > self.last_known_ltp else "S"
            else:
                if self.profile.name == "Momentum Trader":
                    side = "B" if trend == "bullish" else "S" if trend == "bearish" else ("B" if random.random() < 0.5 else "S")
                elif self.profile.name in ["Contrarian Buyer", "Contrarian Seller"]:
                    if trend == "bullish" and self.profile.name == "Contrarian Seller":
                        side = "S"
                    elif trend == "bearish" and self.profile.name == "Contrarian Buyer":
                        side = "B"
                    else:
                        side = "B" if self.personal_price > self.last_known_ltp else "S"
                else:
                    diff = self.personal_price - self.last_known_ltp
                    side = "S" if diff < 0 else "B"

            order_price = self.profile.compute_order_price(
                bot=self,
                side=side,
                best_bid_price=best_bid_price,
                best_ask_price=best_ask_price
            )

            base_qty = random.randint(config.MIN_ORDER_QTY, config.MAX_ORDER_QTY)
            # t_fraction: fraction of the bot's trading duration elapsed.
            t_fraction = (time.perf_counter() - self.start_time) / self.trading_duration
            # Adjust volume: more orders (or larger volume) at start and end.
            volume_weight = 1 + config.VOLUME_PEAK_FACTOR * (4 * (t_fraction - 0.5)**2)
            quantity = max(1, int(base_qty * self.profile.volume_multiplier * volume_weight))

            # Log market info.
            self.log.info(
                f"Market Info: LTP={self.engine.last_traded_price:.2f}, Best Bid Vol={bid_volume}, Best Ask Vol={ask_volume}"
            )

            # Enforce position limits.
            if side == "B" and self.position >= config.POSITION_LIMIT:
                self.log.info(f"Skipping BUY order: Position limit reached ({self.position} >= {config.POSITION_LIMIT}).")
                continue
            elif side == "S" and self.position <= -config.POSITION_LIMIT:
                self.log.info(f"Skipping SELL order: Position limit reached ({self.position} <= -{config.POSITION_LIMIT}).")
                continue

            action = random.choices(
                ["new", "edit", "cancel"],
                weights=[self.profile.order_frequency, 0.5, self.profile.cancellation_rate],
                k=1
            )[0]

            if action == "new":
                order = self.engine.process_order(side, order_price, quantity, owner=None)
                if order:
                    self.active_orders[order.id] = order
                    self.log.info(
                        f"N: Placed new order {order} (Fair={order_price:.2f}, Mkt={current_market:.2f}) using {self.profile.name}"
                    )
                else:
                    self.log.info(
                        f"N: Order fully executed on placement (Fair={order_price:.2f}, Mkt={current_market:.2f}) using {self.profile.name}"
                    )
            elif action == "edit" and self.active_orders:
                order_id = random.choice(list(self.active_orders.keys()))
                order = self.active_orders[order_id]
                if order.active:
                    new_offset = random.uniform(-0.01, 0.01)
                    new_price = enforce_tick(order.price + new_offset)
                    new_quantity = max(1, order.quantity + random.randint(-1, 1))
                    success = self.engine.order_book.edit_order(order_id, new_price=new_price, new_quantity=new_quantity)
                    if success:
                        self.log.info(f"M: Edited order {order_id} to {new_price:.2f} @ {new_quantity}")
                    else:
                        self.log.info(f"M: Failed to edit order {order_id}")
            elif action == "cancel" and self.active_orders:
                order_id = random.choice(list(self.active_orders.keys()))
                order = self.active_orders[order_id]
                if order.active:
                    success = self.engine.order_book.cancel_order(order_id)
                    if success:
                        self.log.info(f"X: Cancelled order {order_id}")
                        del self.active_orders[order_id]
                    else:
                        self.log.info(f"X: Failed to cancel order {order_id}")

            # Calculate order delay by combining multiple factors.
            effective_frequency = self.profile.order_frequency

            if volatility > config.VOLATILITY_THRESHOLD:
                effective_frequency *= 1.5  # More aggressive trading when volatile.

            base_interval = config.TICK_INTERVAL * (1 / effective_frequency)
            reaction_adjusted_interval = base_interval * self.profile.reaction_speed
            day_phase_factor = 1 + config.VOLUME_PEAK_FACTOR * (4 * (t_fraction - 0.5)**2)
            order_delay_min = reaction_adjusted_interval
            order_delay_max = 1.5 * reaction_adjusted_interval * day_phase_factor
            sleep_time = random.uniform(order_delay_min, order_delay_max)
            time.sleep(sleep_time)


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
