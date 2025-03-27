# bot_trader.py
import time, random, math, logging
import config
from utils import enforce_tick
from trade_profile import PASSIVE, TraderProfile

class BotTrader:
    def __init__(self, bot_id, engine, profile: TraderProfile = None, mu=0.0, sigma=0.001):
        self.bot_id = bot_id
        self.engine = engine
        # Each bot starts with a slightly randomized fair value.
        self.personal_price = config.INITIAL_PRICE + random.uniform(-1.0, 1.0)
        self.mu = mu
        self.sigma = sigma
        self.profile = profile if profile is not None else PASSIVE
        self.last_known_ltp = config.INITIAL_PRICE
        self.position = 0  
        self.log = logging.getLogger(f"bot_{bot_id}")
        self.active_orders = {}

    def update_personal_price(self):
        """
        Update the bot's personal fair value using a GBM-like random walk plus mild feedback toward the last known LTP.
        """
        Z = random.normalvariate(0, 1)
        effective_sigma = self.sigma * self.profile.price_sensitivity
        new_price = self.personal_price * math.exp(
            (self.mu - 0.5 * effective_sigma**2) * self.profile.tick_interval +
            effective_sigma * math.sqrt(self.profile.tick_interval) * Z
        )
        alpha = 0.05  # Lower alpha gives smoother adjustment
        new_price += alpha * (self.last_known_ltp - new_price)
        self.personal_price = enforce_tick(new_price)

    def check_position_limit(self, proposed_side):
        limit = config.POSITION_LIMIT
        if proposed_side == "B" and self.position >= limit:
            return "S"
        elif proposed_side == "S" and self.position <= -limit:
            return "B"
        return proposed_side

    def run(self, duration=30):
        start_time = time.perf_counter()
        while (time.perf_counter() - start_time) < duration:
            self.update_personal_price()

            if self.engine.last_traded_price is not None:
                self.last_known_ltp = self.engine.last_traded_price

            best_bid_price, _ = self.engine.order_book.get_best_bid()
            best_ask_price, _ = self.engine.order_book.get_best_ask()
            current_market = self.engine.order_book.get_market_price()
            diff = self.personal_price - current_market

            slope_factor = 0.05
            prob_buy = 0.5 - slope_factor * diff
            prob_buy = max(0.0, min(1.0, prob_buy))
            side = "B" if random.random() < prob_buy else "S"

            order_price = self.profile.compute_order_price(
                bot=self,
                side=side,
                best_bid_price=best_bid_price,
                best_ask_price=best_ask_price
            )

            # Compute a base order quantity.
            base_qty = random.randint(config.MIN_ORDER_QTY, config.MAX_ORDER_QTY)
            # Apply volume trend: higher volumes at start and end of day.
            t_fraction = (time.perf_counter() - start_time) / duration  # normalized [0,1]
            # U-shaped envelope: peak at t=0 and t=1, minimum at t=0.5.
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
