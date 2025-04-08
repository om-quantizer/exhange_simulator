# bot_trader.py
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

        start_time = time.perf_counter()
        last_profile_update = start_time  # record the last time the profile was updated
        update_interval = 120  # seconds between dynamic profile updates

        while (time.perf_counter() - start_time) < duration:
            # If circuit breaker active, cancel orders and pause
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


            # Dynamic profile update during the day:
            current_time = time.perf_counter()
            if current_time - last_profile_update >= update_interval:
                # Generate new dynamic weights by perturbing the base weights stored in the engine.
                dynamic_weights = [max(0, w + random.uniform(-0.05, 0.05)) for w in self.engine.base_weights]
                total = sum(dynamic_weights)
                normalized_weights = [w / total for w in dynamic_weights]
                old_profile = self.profile.name
                # Reassign profile using the updated weights.
                self.profile = random.choices(self.engine.profiles, weights=normalized_weights, k=1)[0]
                last_profile_update = current_time
                self.log.info(f"Dynamic profile update: Changed from {old_profile} to {self.profile.name}")


            best_bid_price, _ = self.engine.order_book.get_best_bid()
            best_ask_price, _ = self.engine.order_book.get_best_ask()
            current_market = self.engine.order_book.get_market_price()

            # Determine trading side based on profile and market trend
            if self.profile.name == "Momentum Trader":
                trend = self.engine.update_trend_indicator(self.engine.last_traded_price)
                side = "B" if trend == "bullish" else "S" if trend == "bearish" else ("B" if random.random() < 0.5 else "S")
            
            elif self.profile.name in ["Contrarian Buyer", "Contrarian Seller"]:
                trend = self.engine.update_trend_indicator(self.engine.last_traded_price)
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
            t_fraction = (time.perf_counter() - start_time) / duration
            volume_weight = 1 + config.VOLUME_PEAK_FACTOR * (1 - 4 * (t_fraction - 0.5)**2)
            quantity = max(1, int(base_qty * self.profile.volume_multiplier * volume_weight))

            action = random.choices(
                ["new", "edit", "cancel"],
                weights=[self.profile.order_frequency, 0.5, self.profile.cancellation_rate],
                k=1
            )[0]

            if action == "new":
                order = self.engine.process_order(side, order_price, quantity, owner=None)
                if order:
                    self.active_orders[order.id] = order
                    self.log.info(f"N: Placed new order {order} (Fair={order_price:.2f}, Mkt={current_market:.2f}) using {self.profile.name}")
                else:
                    self.log.info(f"N: Order fully executed on placement (Fair={order_price:.2f}, Mkt={current_market:.2f}) using {self.profile.name}")
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

            sleep_time = random.uniform(self.profile.reaction_speed, 1.5 * self.profile.reaction_speed)
            time.sleep(sleep_time)
