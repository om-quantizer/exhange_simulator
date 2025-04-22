# order_book.py
# In-memory order book with FIFO Price-Time priority matching, edit/cancel support, 
# and snapshot logging of bids/asks for visualization.

from collections import deque
import network
from utils import get_next_order_id, current_timestamp_ns, enforce_tick
import config
import logging
import datetime

class Order:
    """Represents an order in the order book."""
    def __init__(self, side, price, quantity, owner=None):
        self.id = get_next_order_id()  # Unique order ID.
        self.symbol = config.SYMBOL
        self.side = side               # 'B' for Buy, 'S' for Sell.
        self.price = enforce_tick(price)
        self.quantity = quantity
        self.timestamp_ns = current_timestamp_ns()  # High-resolution timestamp.
        self.owner = owner             # TCP connection or None.
        self.active = True             # True if order is live.

    def __repr__(self):
        return (f"Order(id={self.id}, side={self.side}, price={self.price:.2f}, "
                f"qty={self.quantity}, active={self.active})")

class OrderBook:
    """Holds buy and sell orders grouped by price level."""
    def __init__(self):
        self.bids = {}            # price -> deque of buy orders.
        self.asks = {}            # price -> deque of sell orders.
        self.orders_by_id = {}    # Lookup table for orders.
        # A dedicated logger for snapshots:
        self.lob_logger = logging.getLogger("orderbook")

    def add_order(self, side, price, quantity, owner=None):
        """Create and add a new order, broadcasting a New Order message."""
        order = Order(side, price, quantity, owner)
        self._add_to_book(order)
        network.send_order(order)
        return order

    def _add_to_book(self, order):
        """Internal: add an order to the appropriate book and lookup."""
        price_key = enforce_tick(order.price)
        if order.side == 'B':
            if price_key not in self.bids:
                self.bids[price_key] = deque()
            self.bids[price_key].append(order)
        else:
            if price_key not in self.asks:
                self.asks[price_key] = deque()
            self.asks[price_key].append(order)
        self.orders_by_id[order.id] = order

    def add_existing_order(self, order):
        """
        Add an order that already exists (e.g. a partially filled order) while preserving its ID.
        """
        self._add_to_book(order)
        network.send_order(order)
        return order

    def remove_order(self, order_id):
        """Remove an order from the book (e.g. after full execution or cancellation)."""
        order = self.orders_by_id.pop(order_id, None)
        if not order:
            return None
        price_key = enforce_tick(order.price)
        if order.side == 'B':
            dq = self.bids.get(price_key)
            if dq:
                self._remove_from_deque(dq, order_id)
                if not dq:
                    self.bids.pop(price_key, None)
        else:
            dq = self.asks.get(price_key)
            if dq:
                self._remove_from_deque(dq, order_id)
                if not dq:
                    self.asks.pop(price_key, None)
        return order

    def _remove_from_deque(self, dq, order_id):
        """Helper to remove order from a deque."""
        for o in list(dq):
            if o.id == order_id:
                dq.remove(o)
                break

    def cancel_order(self, order_id):
        """Cancel an order. Marks the order inactive and broadcasts a cancellation ack."""
        order = self.orders_by_id.get(order_id)
        if not order or not order.active:
            return False
        order.active = False
        self.remove_order(order_id)
        network.send_cancel(order)
        network.send_cancel_ack(order)  # Send cancellation acknowledgement.
        return True

    def edit_order(self, order_id, new_price=None, new_quantity=None):
        """
        Edit an active order. If the order is already cancelled or fully executed, reject the edit.
        Broadcast an edit acknowledgment (edit_ack) on success.
        """
        order = self.orders_by_id.get(order_id)
        if not order or not order.active:
            return False
        # Remove the order from its current price level.
        self.remove_order(order_id)
        # Update the order attributes.
        if new_price is not None:
            order.price = enforce_tick(new_price)
        if new_quantity is not None:
            order.quantity = new_quantity
        order.timestamp_ns = current_timestamp_ns()  # Update time for re-prioritization.
        # Add the modified order back.
        self._add_to_book(order)
        network.send_edit_ack(order)
        return True

    def cancel_all(self):
        """Utility to cancel all active orders (if needed)."""
        for order_id in list(self.orders_by_id.keys()):
            self.cancel_order(order_id)

    def get_best_bid(self):
        """Return the best (highest) bid price and cumulative quantity."""
        if not self.bids:
            return None, 0
        best_price = max(self.bids.keys())
        # Take a snapshot copy of the orders at this price level
        orders_at_best = list(self.bids[best_price])
        total_qty = sum(o.quantity for o in orders_at_best if o is not None and hasattr(o, "quantity"))
        return best_price, total_qty

    def get_best_ask(self):
        """Return the best (lowest) ask price and cumulative quantity."""
        if not self.asks:
            return None, 0
        best_price = min(self.asks.keys())
        # Take a snapshot of the current orders at this price level.
        orders_at_best = list(self.asks[best_price])
        total_qty = sum(o.quantity for o in orders_at_best if o is not None and hasattr(o, "quantity"))
        return best_price, total_qty

    def get_market_price(self):
        """
        Compute the market price using order book imbalance for better accuracy.
        If both bid and ask exist:
            - Uses mid-price adjusted by liquidity imbalance.
        If only one side exists:
            - Returns that side’s price.
        If neither exists, return INITIAL_PRICE from config.
        """
        best_bid, bid_qty = self.get_best_bid()
        best_ask, ask_qty = self.get_best_ask()

        if best_bid is not None and best_ask is not None:
            mid_price = (best_bid + best_ask) / 2
            total_qty = bid_qty + ask_qty
            if total_qty > 0:
                weighted_price = (bid_qty * best_bid + ask_qty * best_ask) / total_qty
            else:
                weighted_price = mid_price
            smoothed_price = (mid_price + weighted_price) / 2
            return enforce_tick(smoothed_price)

        return best_bid if best_bid is not None else best_ask if best_ask is not None else config.INITIAL_PRICE

    def log_snapshot(self, depth=10):
        """
        Log the current order book state (bids and asks) up to a certain depth.
        This writes lines to the 'orderbook' logger (order_book.log).
        Format: SNAPSHOT,<timestamp>,SIDE,price,volume
        """
        import datetime
        timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        
        # Bids: descending order by price
        sorted_bids = sorted(self.bids.keys(), reverse=True)
        bid_count = 0
        for price_level in sorted_bids:
            if bid_count >= depth:
                break
            # Take a snapshot copy of the deque to avoid concurrent modification issues.
            orders_at_price = list(self.bids[price_level])
            total_vol = sum(o.quantity for o in orders_at_price 
                            if o is not None and hasattr(o, "quantity"))
            self.lob_logger.info(f"SNAPSHOT,{timestamp_str},BID,{price_level:.2f},{total_vol}")
            bid_count += 1

        # Asks: ascending order by price
        sorted_asks = sorted(self.asks.keys())
        ask_count = 0
        for price_level in sorted_asks:
            if ask_count >= depth:
                break
            orders_at_price = list(self.asks[price_level])
            total_vol = sum(o.quantity for o in orders_at_price 
                            if o is not None and hasattr(o, "quantity"))
            self.lob_logger.info(f"SNAPSHOT,{timestamp_str},ASK,{price_level:.2f},{total_vol}")
            ask_count += 1


    # NEW method: log best bid/ask at the moment
    def log_best_prices(self):
        best_bid, bid_qty = self.get_best_bid()
        best_ask, ask_qty = self.get_best_ask()
        timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        self.lob_logger.info(
            f"BEST_PRICES,{timestamp_str},BID={best_bid},QTY={bid_qty},ASK={best_ask},QTY={ask_qty}"
        )

# from collections import deque
# import network
# from utils import get_next_order_id, current_timestamp_ns, enforce_tick
# import config
# import logging
# import datetime

# class Order:
#     """Represents an order in the order book."""
#     def __init__(self, side, price, quantity, owner=None):
#         self.id = get_next_order_id()  # Unique order ID.
#         self.symbol = config.SYMBOL
#         self.side = side               # 'B' for Buy, 'S' for Sell.
#         self.price = enforce_tick(price)
#         self.quantity = quantity
#         self.timestamp_ns = current_timestamp_ns()  # High-resolution timestamp.
#         self.owner = owner             # TCP connection or BotTrader.
#         self.active = True

#     def __repr__(self):
#         return (f"Order(id={self.id}, side={self.side}, price={self.price:.2f}, "
#                 f"qty={self.quantity}, active={self.active})")

# class OrderBook:
#     """Maintains the order book with FIFO price-time priority."""
#     def __init__(self):
#         self.bids = {}           
#         self.asks = {}           
#         self.orders_by_id = {}  
#         self.lob_logger = logging.getLogger("orderbook")

#     def add_order(self, side, price, quantity, owner=None):
#         order = Order(side, price, quantity, owner)
#         self._add_to_book(order)
#         network.send_order(order)
#         return order

#     def _add_to_book(self, order):
#         price_key = enforce_tick(order.price)
#         if order.side == 'B':
#             if price_key not in self.bids:
#                 self.bids[price_key] = deque()
#             self.bids[price_key].append(order)
#         else:
#             if price_key not in self.asks:
#                 self.asks[price_key] = deque()
#             self.asks[price_key].append(order)
#         self.orders_by_id[order.id] = order

#     def add_existing_order(self, order):
#         self._add_to_book(order)
#         network.send_order(order)
#         return order

#     def remove_order(self, order_id):
#         order = self.orders_by_id.pop(order_id, None)
#         if not order:
#             return None
#         price_key = enforce_tick(order.price)
#         if order.side == 'B':
#             dq = self.bids.get(price_key)
#             if dq:
#                 self._remove_from_deque(dq, order_id)
#                 if not dq:
#                     self.bids.pop(price_key, None)
#         else:
#             dq = self.asks.get(price_key)
#             if dq:
#                 self._remove_from_deque(dq, order_id)
#                 if not dq:
#                     self.asks.pop(price_key, None)
#         return order

#     def _remove_from_deque(self, dq, order_id):
#         for o in list(dq):
#             if o.id == order_id:
#                 dq.remove(o)
#                 break

#     def cancel_order(self, order_id):
#         order = self.orders_by_id.get(order_id)
#         if not order or not order.active:
#             return False
#         order.active = False
#         self.remove_order(order_id)
#         network.send_cancel(order)
#         network.send_cancel_ack(order)
#         return True

#     def edit_order(self, order_id, new_price=None, new_quantity=None):
#         order = self.orders_by_id.get(order_id)
#         if not order or not order.active:
#             return False
#         self.remove_order(order_id)
#         if new_price is not None:
#             order.price = enforce_tick(new_price)
#         if new_quantity is not None:
#             order.quantity = new_quantity
#         order.timestamp_ns = current_timestamp_ns()
#         self._add_to_book(order)
#         network.send_edit_ack(order)
#         return True

#     def cancel_all(self):
#         for order_id in list(self.orders_by_id.keys()):
#             self.cancel_order(order_id)

#     def get_best_bid(self):
#         if not self.bids:
#             return None, 0
#         best_price = max(self.bids.keys())
#         orders_at_best = list(self.bids[best_price])
#         total_qty = sum(o.quantity for o in orders_at_best if hasattr(o, "quantity"))
#         return best_price, total_qty

#     def get_best_ask(self):
#         if not self.asks:
#             return None, 0
#         best_price = min(self.asks.keys())
#         orders_at_best = list(self.asks[best_price])
#         total_qty = sum(o.quantity for o in orders_at_best if hasattr(o, "quantity"))
#         return best_price, total_qty

#     def get_market_price(self):
#         best_bid, bid_qty = self.get_best_bid()
#         best_ask, ask_qty = self.get_best_ask()

#         if best_bid is not None and best_ask is not None:
#             mid_price = (best_bid + best_ask) / 2
#             total_qty = bid_qty + ask_qty
#             if total_qty > 0:
#                 weighted_price = (bid_qty * best_bid + ask_qty * best_ask) / total_qty
#             else:
#                 weighted_price = mid_price
#             smoothed_price = (mid_price + weighted_price) / 2
#             if bid_qty < config.MIN_LIQUIDITY_THRESHOLD or ask_qty < config.MIN_LIQUIDITY_THRESHOLD:
#                 smoothed_price *= config.SPREAD_MULTIPLIER
#             return enforce_tick(smoothed_price)

#         return best_bid if best_bid is not None else best_ask if best_ask is not None else config.INITIAL_PRICE

#     def log_snapshot(self, depth=10):
#         timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
#         sorted_bids = sorted(self.bids.keys(), reverse=True)
#         bid_count = 0
#         for price_level in sorted_bids:
#             if bid_count >= depth:
#                 break
#             orders_at_price = list(self.bids[price_level])
#             total_vol = sum(o.quantity for o in orders_at_price if hasattr(o, "quantity"))
#             self.lob_logger.info(f"SNAPSHOT,{timestamp_str},BID,{price_level:.2f},{total_vol}")
#             bid_count += 1

#         sorted_asks = sorted(self.asks.keys())
#         ask_count = 0
#         for price_level in sorted_asks:
#             if ask_count >= depth:
#                 break
#             orders_at_price = list(self.asks[price_level])
#             total_vol = sum(o.quantity for o in orders_at_price if hasattr(o, "quantity"))
#             self.lob_logger.info(f"SNAPSHOT,{timestamp_str},ASK,{price_level:.2f},{total_vol}")
#             ask_count += 1

#     def log_best_prices(self):
#         best_bid, bid_qty = self.get_best_bid()
#         best_ask, ask_qty = self.get_best_ask()
#         timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
#         self.lob_logger.info(
#             f"BEST_PRICES,{timestamp_str},BID={best_bid},QTY={bid_qty},ASK={best_ask},QTY={ask_qty}"
#         )
