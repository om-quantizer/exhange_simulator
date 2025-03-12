# bot_trader.py
import time
import random
import logging
import config
from utils import enforce_tick


class BotTrader:
    def __init__(self, bot_id, engine, market_data):
        self.bot_id = bot_id
        self.engine = engine
        self.market_data = market_data
        self.log = logging.getLogger(f"bot_{bot_id}")
        self.active_orders = {}  # Mapping from order ID to order object

    def run(self, duration=30):
        start_time = time.time()
        while time.time() - start_time < duration:
            action = random.choice(["new", "edit", "cancel"])
            if action == "new":
                # Generate a new order: randomly choose side, price near market price, random quantity.
                side = random.choice(["B", "S"])
                market_price = self.market_data.get_price()
                price = market_price * random.uniform(0.99, 1.01)
                # price = enforce_tick(price)
                quantity = random.randint(1, 10)
                order = self.engine.process_order(side, price, quantity, owner=None)
                order.price=order.price
                if order:
                    self.active_orders[order.id] = order
                    self.log.info(f"Placed new order: {order}")
            elif action == "edit" and self.active_orders:
                # Randomly select an active order and attempt to edit it.
                order_id = random.choice(list(self.active_orders.keys()))
                order = self.active_orders[order_id]
                if order.active:
                    # Generate new price and quantity.
                    new_price = order.price * random.uniform(0.98, 1.02)
                    new_price = enforce_tick(new_price)
                    new_quantity = order.quantity + random.randint(-1, 2)
                    new_quantity = max(new_quantity, 1)
                    success = self.engine.order_book.edit_order(order_id, new_price=new_price, new_quantity=new_quantity)
                    if success:
                        self.log.info(f"Edited order {order_id}: new price {new_price:.2f}, new quantity {new_quantity}")
                    else:
                        self.log.info(f"Failed to edit order {order_id}")
            elif action == "cancel" and self.active_orders:
                # Randomly select an active order to cancel.
                order_id = random.choice(list(self.active_orders.keys()))
                order = self.active_orders[order_id]
                if order.active:
                    success = self.engine.order_book.cancel_order(order_id)
                    if success:
                        self.log.info(f"Cancelled order {order_id}")
                        del self.active_orders[order_id]
                    else:
                        self.log.info(f"Failed to cancel order {order_id}")
            time.sleep(random.uniform(0.1, 0.5))
