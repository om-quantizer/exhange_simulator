# order_book.py
# In-memory order book with FIFO Price-Time priority matching and edit/cancel support.
from collections import deque
import network
from utils import get_next_order_id, current_timestamp_ns, enforce_tick 
import config

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
        return f"Order(id={self.id}, side={self.side}, price={self.price:.2f}, qty={self.quantity}, active={self.active})"

class OrderBook:
    """Holds buy and sell orders grouped by price level."""
    def __init__(self):
        self.bids = {}            # price -> deque of buy orders.
        self.asks = {}            # price -> deque of sell orders.
        self.orders_by_id = {}    # Lookup table for orders.

    def add_order(self, side, price, quantity, owner=None):
        """Create and add a new order, broadcasting a New Order message."""
        order = Order(side, price, quantity, owner)
        self._add_to_book(order)
        network.send_order(order)
        return order

    def _add_to_book(self, order):
        """Internal: add an order to the appropriate book and lookup."""
        if order.side == 'B':
            if order.price not in self.bids:
                self.bids[enforce_tick(order.price)] = deque()
            self.bids[enforce_tick(order.price)].append(order)
        else:
            if order.price not in self.asks:
                self.asks[order.price] = deque()
            self.asks[order.price].append(order)
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
        if order.side == 'B':
            dq = self.bids.get(order.price)
            if dq:
                self._remove_from_deque(dq, order_id)
                if not dq:
                    self.bids.pop(order.price, None)
        else:
            dq = self.asks.get(order.price)
            if dq:
                self._remove_from_deque(dq, order_id)
                if not dq:
                    self.asks.pop(order.price, None)
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
            order.price = new_price
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
        total_qty = sum(o.quantity for o in self.bids[best_price])
        return best_price, total_qty

    def get_best_ask(self):
        """Return the best (lowest) ask price and cumulative quantity."""
        if not self.asks:
            return None, 0
        best_price = min(self.asks.keys())
        total_qty = sum(o.quantity for o in self.asks[best_price])
        return best_price, total_qty

