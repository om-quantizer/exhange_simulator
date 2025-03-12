# matching_engine.py
# Order matching engine with FIFO price-time priority.
# FIXED: Properly executes trades when orders overlap and broadcasts every trade,
# and now logs explicit trade details. Also uses the same Order ID for partially filled orders.

import logging
from collections import deque
import threading
from utils import enforce_tick
import network

class MatchingEngine:
    def __init__(self, order_book):
        self.order_book = order_book
        self.log = logging.getLogger("exchange")
        self.lock = threading.Lock()  # Ensure thread-safe order processing

    def process_order(self, side, price, quantity, owner=None):
        """
        Process an incoming order by matching it against the opposite side.
        Executes trades until fully filled or unmatched volume remains.
        Each trade is broadcast via UDP and now logged with details.
        Returns the remaining order (if not fully matched) or None if fully filled.
        """
        from order_book import Order
        # Create the incoming order (order ID is set inside Order)
        incoming_order = Order(side, price, quantity, owner)
        # incoming_order.price=enforce_tick(incoming_order.price)
        network.send_order(incoming_order)  # Broadcast the new order.
        remaining_qty = quantity

        with self.lock:
            if side == 'B':
                # Buy order: try to match with the lowest sell prices.
                while remaining_qty > 0:
                    best_ask_price, _ = self.order_book.get_best_ask()
                    if best_ask_price is None or best_ask_price > price:
                        break  # No matching sell orders available.

                    sell_queue = self.order_book.asks[best_ask_price]
                    best_sell = sell_queue[0]  # FIFO: first order at that price.
                    trade_qty = min(remaining_qty, best_sell.quantity)
                    trade_price = enforce_tick(best_ask_price)

                    # Execute trade
                    best_sell.quantity -= trade_qty
                    remaining_qty -= trade_qty

                    # Broadcast the trade via UDP.
                    network.send_trade(buy_id=incoming_order.id, sell_id=best_sell.id,
                                       trade_price=trade_price, trade_qty=trade_qty)

                    # Send TCP confirmation if the buyer/seller is a client.
                    self._send_trade_confirmation(incoming_order, best_sell, trade_qty, trade_price)

                    # Log the trade details explicitly.
                    self.log.info(f"Trade executed: Buy Order {incoming_order.id} and Sell Order {best_sell.id} "
                                  f"for {trade_qty} units at {trade_price:.2f}")

                    # Remove fully filled sell order.
                    if best_sell.quantity == 0:
                        self.order_book.remove_order(best_sell.id)

                # If there's unmatched quantity, add the remaining portion to the order book.
                if remaining_qty > 0:
                    incoming_order.quantity = remaining_qty
                    # Use add_existing_order to preserve the same order id.
                    self.order_book.add_existing_order(incoming_order)
                    return incoming_order
                else:
                    return None  # Order fully matched.

            else:
                # Sell order: try to match with the highest buy prices.
                while remaining_qty > 0:
                    best_bid_price, _ = self.order_book.get_best_bid()
                    if best_bid_price is None or best_bid_price < price:
                        break  # No matching buy orders available.

                    buy_queue = self.order_book.bids[best_bid_price]
                    best_buy = buy_queue[0]  # FIFO: first order at that price.
                    trade_qty = min(remaining_qty, best_buy.quantity)
                    trade_price = enforce_tick(best_bid_price)

                    # Execute trade
                    best_buy.quantity -= trade_qty
                    remaining_qty -= trade_qty

                    network.send_trade(buy_id=best_buy.id, sell_id=incoming_order.id,
                                       trade_price=trade_price, trade_qty=trade_qty)

                    self._send_trade_confirmation(best_buy, incoming_order, trade_qty, trade_price)

                    self.log.info(f"Trade executed: Sell Order {incoming_order.id} and Buy Order {best_buy.id} "
                                  f"for {trade_qty} units at {trade_price:.2f}")

                    if best_buy.quantity == 0:
                        self.order_book.remove_order(best_buy.id)

                if remaining_qty > 0:
                    incoming_order.quantity = remaining_qty
                    self.order_book.add_existing_order(incoming_order)
                    return incoming_order
                else:
                    return None  # Order fully matched.

    def _send_trade_confirmation(self, buy_order, sell_order, quantity, price):
        """Send TCP trade confirmation to clients if applicable."""
        if buy_order.owner is not None:
            try:
                buy_order.owner.sendall(
                    f"TRADE CONFIRM: Bought {quantity} @ {price}\n".encode()
                )
            except Exception as e:
                self.log.error(f"Error sending trade confirmation to buyer: {e}")

        if sell_order.owner is not None:
            try:
                sell_order.owner.sendall(
                    f"TRADE CONFIRM: Sold {quantity} @ {price}\n".encode()
                )
            except Exception as e:
                self.log.error(f"Error sending trade confirmation to seller: {e}")
