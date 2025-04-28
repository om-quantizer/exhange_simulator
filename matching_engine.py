# matching_engine.py
# Module: MatchingEngine
# Description:
#   - Handles incoming orders from bots and clients.
#   - Matches buy and sell orders using FIFO price-time priority.
#   - Applies limit checks, trading bands, and TER (trading range) constraints.
#   - Implements circuit breaker logic for volatility control.
#   - Broadcasts orders, trades, cancelations over UDP multicast via network module.
#   - Maintains moving average trend indicators for bots to reference.

import logging                # Standard logging module for engine and trade logs
import threading             # For thread synchronization and timers
import time                   # For high-resolution timing (perf_counter) and sleep
import random                 # For random slippage, shock injection, and order price adjustments
import network                # Custom module to multicast feed messages over UDP
from utils import (
    enforce_tick,             # Rounds a price to nearest configured tick increment
    trigger_circuit_breaker,  # Activates circuit breaker and schedules reset
    reset_circuit_breaker     # Resets circuit breaker after cooldown
)
import config                 # Global configuration parameters (thresholds, durations, etc.)
from collections import deque # Deque for maintaining fixed-length price history for trend detection
import math                   # For mathematical operations (exp, sqrt) in trend indicator

class MatchingEngine:
    """
    Core matching engine managing order execution and market state.

    Responsibilities:
      - Validate incoming orders against daily bands and TER range.
      - Match orders via interacting with the OrderBook instance.
      - Handle partial fills: unfilled portions re-enter the book.
      - Apply slippage and market impact for each trade execution.
      - Broadcast market data (orders, trades, cancels) via UDP multicast.
      - Trigger and reset circuit breaker when price limit reached.
      - Compute simple moving average trend indicators for trading bots.
    """
    def __init__(self, order_book):
        # Reference to OrderBook storing active bids and asks
        self.order_book = order_book

        # Logger for high-level engine events (info, warnings)
        self.log = logging.getLogger("exchange")
        # Logger dedicated to detailed trade entries (fills, execution prices)
        self.trade_logger = logging.getLogger("trade")

        # Initialize last traded price to simulation start price
        self.last_traded_price = config.INITIAL_PRICE

        # Thread-safe lock to sequence critical sections during matching
        self.lock = threading.Lock()

        # Record the price at the beginning of trading day
        self.daily_open_price = config.INITIAL_PRICE
        # Maximum allowed move percentage around open
        self.current_band_percent = config.MAX_DAILY_MOVE_PERCENT
        # Compute absolute bounds based on open and band percent
        self.daily_lower_bound = self.daily_open_price * (1 - self.current_band_percent/100)
        self.daily_upper_bound = self.daily_open_price * (1 + self.current_band_percent/100)

        # Circuit breaker initial state: inactive with no trigger timestamp
        self.circuit_active = False
        self.circuit_trigger_time = None

        # Maintain a rolling window of recent prices for trend detection
        self.price_history = deque(maxlen=200)  # Only keep last 200 ticks

    def reset_for_new_day(self, new_open_price):
        """
        Reset engine state at start of each simulation day:
          - Update daily open price and reset band limits
          - Clear circuit breaker flag
          - Initialize price history with opening price
        Args:
            new_open_price (float): Price at which new day begins
        """
        with self.lock:
            # Update open price and recalculate band boundaries
            self.daily_open_price = new_open_price
            self.current_band_percent = config.MAX_DAILY_MOVE_PERCENT
            self.daily_lower_bound = new_open_price * (1 - self.current_band_percent/100)
            self.daily_upper_bound = new_open_price * (1 + self.current_band_percent/100)

            # Reset circuit breaker variables
            self.circuit_active = False
            self.circuit_trigger_time = None

            # Reset price history deque and seed with opening price
            self.price_history.clear()
            self.price_history.append(new_open_price)

            # Log the state for debugging and verification
            self.log.info(
                f"New day started: Open={new_open_price:.2f}, "
                f"Band=±{self.current_band_percent}% (" \
                f"{self.daily_lower_bound:.2f}-{self.daily_upper_bound:.2f})"
            )

    def expand_daily_band(self):
        """
        Increase allowed daily band when a circuit triggers or news shock occurs.
        Expands current_band_percent by configured increment and updates bounds.
        """
        self.current_band_percent += config.BAND_EXPANSION_INCREMENT
        # Recompute absolute bounds from open price
        self.daily_lower_bound = self.daily_open_price * (1 - self.current_band_percent/100)
        self.daily_upper_bound = self.daily_open_price * (1 + self.current_band_percent/100)
        # Log new band details
        self.log.info(
            f"Daily band expanded to ±{self.current_band_percent}%. "
            f"Bounds:[{self.daily_lower_bound:.2f}-{self.daily_upper_bound:.2f}]"
        )

    def get_market_trend(self) -> str:
        """
        Simple trend measure relative to the daily open price:
          - Bullish if last_traded_price > open + 0.5% of open
          - Bearish if last_traded_price < open - 0.5% of open
          - Sideways otherwise
        Returns:
            str: 'bullish', 'bearish', or 'sideways'
        """
        threshold = 0.005 * self.daily_open_price
        if self.last_traded_price > self.daily_open_price + threshold:
            return "bullish"
        elif self.last_traded_price < self.daily_open_price - threshold:
            return "bearish"
        else:
            return "sideways"

    def update_trend_indicator(self, price: float) -> str:
        """
        Maintain rolling price history and compute short vs. long moving averages:
          - Short MA: average of most recent 20 prices
          - Long MA: average of most recent 100 prices or all if <100
        Compare with small thresholds (±0.1%) to classify trend.
        Args:
            price (float): New price tick to append
        Returns:
            str: 'bullish', 'bearish', or 'sideways'
        """
        self.price_history.append(price)
        # Compute moving averages
        short_window = list(self.price_history)[-20:]
        long_window = (list(self.price_history)[-100:]
                       if len(self.price_history)>=100 else list(self.price_history))
        short_ma = sum(short_window)/len(short_window)
        long_ma = sum(long_window)/len(long_window)

        # Use margins around 1.0% for trend detection
        if short_ma > long_ma * 1.001:
            return "bullish"
        elif short_ma < long_ma * 0.999:
            return "bearish"
        else:
            return "sideways"

    def process_order(self, side: str, limit_price: float, quantity: int, owner=None):
        """
        Main entry point for order submission. Handles:
          1. Circuit breaker enforcement
          2. Broadcasting order to network
          3. Enforcing daily price bands and TER limits
          4. Matching logic with slippage and market impact
          5. Partial vs. full fill handling
          6. Circuit trigger if fill hits a band limit
        Args:
            side (str): 'B' for buy, 'S' for sell
            limit_price (float): Requested limit price
            quantity (int): Order quantity
            owner: Optional TCP connection for client confirmations
        Returns:
            Order or None: Remaining unfilled order re-added to book, else None
        """
        from order_book import Order
        # Wrap incoming parameters into an Order object
        incoming_order = Order(side, limit_price, quantity, owner)

        # 1) Circuit breaker: reject during active break
        if self.circuit_active:
            age = time.perf_counter() - self.circuit_trigger_time
            if age < config.CIRCUIT_BREAKER_DURATION:
                self.log.info("Circuit active: reject order.")
                network.send_rejection(incoming_order)
                return None
            else:
                # Reset circuit after duration elapses
                self.circuit_active = False
                self.circuit_trigger_time = None

        # 2) Broadcast new order over UDP multicast
        network.send_order(incoming_order)
        remaining_qty = quantity

        # 3) Snap price within allowed daily move bounds
        if limit_price < self.daily_lower_bound:
            limit_price = self.daily_lower_bound
        elif limit_price > self.daily_upper_bound:
            limit_price = self.daily_upper_bound
        incoming_order.price = enforce_tick(limit_price)

        # 4) Enforce TER (Trading Range) relative to open
        ter_low = self.daily_open_price*(1-config.TER_PERCENT/100)
        ter_high = self.daily_open_price*(1+config.TER_PERCENT/100)
        if limit_price<ter_low or limit_price>ter_high:
            self.log.info(f"TER violation: {limit_price:.2f} not in [{ter_low:.2f},{ter_high:.2f}].")
            network.send_rejection(incoming_order)
            return None

        # Setup counters for multi-match aggregation
        aggregated_qty = 0
        execution_count = 0

        # 5) Matching under thread lock to protect shared state
        with self.lock:
            if side=='B':  # BUY matching against asks
                # Loop until no quantity left or no viable asks
                while remaining_qty>0:
                    best_ask, ask_total = self.order_book.get_best_ask()
                    if best_ask is None or best_ask>incoming_order.price:
                        break
                    ask_queue = self.order_book.asks[best_ask]
                    # FIFO within price level
                    while remaining_qty>0 and ask_queue:
                        best_sell = ask_queue[0]
                        trade_qty = min(remaining_qty, best_sell.quantity)
                        trade_price=best_ask
                        # 4a) Slippage: random ±half delta based on config
                        slip_pct = config.CLIENT_SLIPPAGE_PERCENT if owner else config.BOT_SLIPPAGE_PERCENT
                        delta = slip_pct/100*trade_price
                        slippage=random.uniform(-delta/2,delta/2)
                        trade_price=enforce_tick(trade_price+slippage)
                        
                        # Update sizes and counters
                        best_sell.quantity -= trade_qty
                        remaining_qty -= trade_qty
                        aggregated_qty += trade_qty
                        execution_count +=1

                        # Network and logging for each execution
                        network.send_trade(buy_id=incoming_order.id,
                                           sell_id=best_sell.id,
                                           trade_price=trade_price,
                                           trade_qty=trade_qty)
                        self._send_trade_confirmation(incoming_order,best_sell,trade_qty,trade_price)
                        self.trade_logger.info(
                            f"T: Trade executed: Buyer Order id {incoming_order.id} and Seller Order id {best_sell.id} "
                            f"for {trade_qty} units at Rs {trade_price:.2f}. LTP={self.last_traded_price:.2f}"
                        )                        
                        self.last_traded_price=trade_price

                        # 6) Circuit trigger if hitting band
                        if trade_price<=self.daily_lower_bound or trade_price>=self.daily_upper_bound:
                            self.log.info("Trigger circuit: band breach.")
                            trigger_circuit_breaker(self)
                            self.expand_daily_band()

                        # Remove fully consumed order
                        if best_sell.quantity==0:
                            self.order_book.remove_order(best_sell.id)
                        else:
                            break

                # After matching: log aggregated activity
                if execution_count>1:
                    self.trade_logger.info(
                        f"T: Aggregated Trade: Incoming BUY order id {incoming_order.id} executed "
                        f"{execution_count} times for total {aggregated_qty} units."
                    )          
                          
                # If leftover, re-add to book
                if remaining_qty>0:
                    incoming_order.quantity=remaining_qty
                    self.order_book.add_existing_order(incoming_order)
                    return incoming_order
                return None

            else:  # SELL side symmetric to BUY above
                while remaining_qty>0:
                    best_bid,bid_total=self.order_book.get_best_bid()
                    if best_bid is None or best_bid<incoming_order.price:
                        break
                    bid_queue=self.order_book.bids[best_bid]
                    while remaining_qty>0 and bid_queue:
                        best_buy=bid_queue[0]
                        trade_qty=min(remaining_qty,best_buy.quantity)
                        trade_price=best_bid
                        slip_pct=config.CLIENT_SLIPPAGE_PERCENT if owner else config.BOT_SLIPPAGE_PERCENT
                        delta=slip_pct/100*trade_price
                        slippage=random.uniform(-delta/2,delta/2)
                        trade_price=enforce_tick(trade_price-slippage)

                        best_buy.quantity-=trade_qty
                        remaining_qty-=trade_qty
                        aggregated_qty+=trade_qty
                        execution_count+=1

                        network.send_trade(buy_id=best_buy.id,
                                           sell_id=incoming_order.id,
                                           trade_price=trade_price,
                                           trade_qty=trade_qty)
                        self._send_trade_confirmation(best_buy,incoming_order,trade_qty,trade_price)
                        self.trade_logger.info(
                            f"T: Aggregated Trade: Incoming SELL order id {incoming_order.id} executed "
                            f"{execution_count} times for total {aggregated_qty} units."
                        )                        
                        self.last_traded_price=trade_price

                        if trade_price<=self.daily_lower_bound or trade_price>=self.daily_upper_bound:
                            self.log.info("Trigger circuit: band breach.")
                            trigger_circuit_breaker(self)
                            self.expand_daily_band()

                        if best_buy.quantity==0:
                            self.order_book.remove_order(best_buy.id)
                        else:
                            break
                if execution_count>1:
                    self.trade_logger.info(
                        f"T: Aggregated Trade: Incoming SELL order id {incoming_order.id} executed "
                        f"{execution_count} times for total {aggregated_qty} units."
                    )
                if remaining_qty>0:
                    incoming_order.quantity=remaining_qty
                    self.order_book.add_existing_order(incoming_order)
                    return incoming_order
                return None

    def _send_trade_confirmation(self, buy_order, sell_order, qty, price):
        """
        Send trade confirmation to TCP clients if they own the order;
        otherwise, log the confirmation locally.
        Args:
            buy_order (Order): Buyer side of trade
            sell_order (Order): Seller side of trade
            qty (int): Quantity executed
            price (float): Execution price
        """
        # Notify buyer
        if buy_order.owner:
            try:
                buy_order.owner.sendall(f"TRADE CONFIRM: Bought {qty}@{price:.2f}\n".encode())
            except Exception as e:
                self.log.error(f"Buyer confirmation failed: {e}")
        # Notify seller
        if sell_order.owner:
            try:
                sell_order.owner.sendall(f"TRADE CONFIRM: Sold {qty}@{price:.2f}\n".encode())
            except Exception as e:
                self.log.error(f"Seller confirmation failed: {e}")


# import logging
# import threading
# import time
# import random
# import network
# from utils import enforce_tick, trigger_circuit_breaker, reset_circuit_breaker
# import config
# from collections import deque
# import math

# class MatchingEngine:
#     def __init__(self, order_book):
#         self.order_book = order_book
#         self.log = logging.getLogger("exchange")
#         self.trade_logger = logging.getLogger("trade")
#         self.last_traded_price = config.INITIAL_PRICE
#         self.lock = threading.Lock()
#         self.daily_open_price = config.INITIAL_PRICE
#         self.current_band_percent = config.MAX_DAILY_MOVE_PERCENT
#         self.daily_lower_bound = self.daily_open_price * (1 - self.current_band_percent / 100)
#         self.daily_upper_bound = self.daily_open_price * (1 + self.current_band_percent / 100)
#         self.circuit_active = False
#         self.circuit_trigger_time = None

#         # Price history for trend indicators.
#         self.price_history = deque(maxlen=200)

#     def reset_for_new_day(self, new_open_price):
#         with self.lock:
#             self.daily_open_price = new_open_price
#             self.last_traded_price = new_open_price
#             self.current_band_percent = config.MAX_DAILY_MOVE_PERCENT
#             self.daily_lower_bound = self.daily_open_price * (1 - self.current_band_percent / 100)
#             self.daily_upper_bound = self.daily_open_price * (1 + self.current_band_percent / 100)
#             self.circuit_active = False
#             self.circuit_trigger_time = None
#             self.price_history.clear()
#             self.price_history.append(new_open_price)
#             self.log.info(f"New day started. Open price={new_open_price:.2f}, Band=±{self.current_band_percent}% "
#                           f"({self.daily_lower_bound:.2f} - {self.daily_upper_bound:.2f})")

#     def expand_daily_band(self):
#         self.current_band_percent += config.BAND_EXPANSION_INCREMENT
#         self.daily_lower_bound = self.daily_open_price * (1 - self.current_band_percent / 100)
#         self.daily_upper_bound = self.daily_open_price * (1 + self.current_band_percent / 100)
#         self.log.info(f"Daily band expanded to ±{self.current_band_percent}%. New bounds: "
#                       f"[{self.daily_lower_bound:.2f}, {self.daily_upper_bound:.2f}]")
        
#     def get_market_trend(self):
#         threshold = 0.005 * self.daily_open_price
#         if self.last_traded_price > self.daily_open_price + threshold:
#             return "bullish"
#         elif self.last_traded_price < self.daily_open_price - threshold:
#             return "bearish"
#         else:
#             return "sideways"

#     def update_trend_indicator(self, price):
#         self.price_history.append(price)
#         short_window = list(self.price_history)[-20:]
#         long_window = list(self.price_history)[-100:] if len(self.price_history) >= 100 else list(self.price_history)
#         short_ma = sum(short_window) / len(short_window)
#         long_ma = sum(long_window) / len(long_window)
#         if short_ma > long_ma * 1.001:
#             return "bullish"
#         elif short_ma < long_ma * 0.999:
#             return "bearish"
#         else:
#             return "sideways"

#     def process_order(self, side, limit_price, quantity, owner=None):
#         from order_book import Order
#         incoming_order = Order(side, limit_price, quantity, owner)
        
#         if self.circuit_active:
#             if time.perf_counter() - self.circuit_trigger_time < config.CIRCUIT_BREAKER_DURATION:
#                 self.log.info("Circuit breaker active. Order rejected.")
#                 network.send_rejection(incoming_order)
#                 return None
#             else:
#                 self.circuit_active = False
#                 self.circuit_trigger_time = None

#         network.send_order(incoming_order)
#         remaining_qty = quantity

#         if limit_price < self.daily_lower_bound:
#             limit_price = self.daily_lower_bound
#         elif limit_price > self.daily_upper_bound:
#             limit_price = self.daily_upper_bound
#         incoming_order.price = enforce_tick(limit_price)

#         ter_lower_bound = self.daily_open_price * (1 - config.TER_PERCENT / 100)
#         ter_upper_bound = self.daily_open_price * (1 + config.TER_PERCENT / 100)
#         if limit_price < ter_lower_bound or limit_price > ter_upper_bound:
#             self.log.info(
#                 f"Order price {limit_price:.2f} outside TER range ({ter_lower_bound:.2f}-{ter_upper_bound:.2f}). Order rejected."
#             )
#             network.send_rejection(incoming_order)
#             return None

#         # Portfolio constraint check.
#         if owner is not None:
#             if side == 'B':
#                 required_cost = incoming_order.price * incoming_order.quantity
#                 if owner.cash < required_cost:
#                     if config.LEVERAGE_ALLOWED:
#                         if required_cost > owner.cash * owner.max_leverage:
#                             self.log.info(f"Order rejected: Buyer Bot {owner.bot_id} exceeds margin limits "
#                                           f"(Required: {required_cost:.2f}, Available: {owner.cash:.2f} x {owner.max_leverage}).")
#                             network.send_rejection(incoming_order)
#                             return None
#                         else:
#                             margin_used = required_cost - owner.cash
#                             owner.debt += margin_used
#                             owner.cash = 0
#                             self.log.info(f"Margin trade: Buyer Bot {owner.bot_id} used margin of {margin_used:.2f}.")
#                     else:
#                         self.log.info(f"Order rejected: Buyer Bot {owner.bot_id} has insufficient cash "
#                                       f"({owner.cash:.2f}) for order cost {required_cost:.2f}.")
#                         network.send_rejection(incoming_order)
#                         return None
#             else:
#                 if owner.shares < incoming_order.quantity:
#                     self.log.info(f"Order rejected: Seller Bot {owner.bot_id} has insufficient shares "
#                                   f"({owner.shares}) for order quantity {incoming_order.quantity}.")
#                     network.send_rejection(incoming_order)
#                     return None

#         aggregated_qty = 0
#         execution_count = 0

#         with self.lock:
#             if side == 'B':
#                 while remaining_qty > 0:
#                     best_ask_price, total_ask_qty = self.order_book.get_best_ask()
#                     if best_ask_price is None or best_ask_price > limit_price:
#                         break
#                     sell_queue = self.order_book.asks[best_ask_price]
#                     while remaining_qty > 0 and sell_queue:
#                         best_sell = sell_queue[0]
#                         trade_qty = min(remaining_qty, best_sell.quantity)
#                         trade_price = best_ask_price
#                         if incoming_order.owner is not None:
#                             slippage_percent = config.CLIENT_SLIPPAGE_PERCENT
#                         else:
#                             slippage_percent = config.BOT_SLIPPAGE_PERCENT
                        
#                         delta = slippage_percent / 100 * trade_price
#                         slippage = random.uniform(-delta/2, delta/2)
#                         trade_price = enforce_tick(trade_price + slippage)
                        
#                         if total_ask_qty > 0:
#                             extra_impact = config.MARKET_IMPACT_COEFFICIENT * (trade_qty / total_ask_qty) * trade_price
#                             trade_price = enforce_tick(trade_price + extra_impact)

#                         # Update portfolios and trade counts.
#                         if incoming_order.owner is not None and best_sell.owner is not None:
#                             cost = trade_price * trade_qty
#                             incoming_order.owner.cash -= cost
#                             incoming_order.owner.shares += trade_qty
#                             incoming_order.owner.trade_count += trade_qty
#                             best_sell.owner.cash += cost
#                             best_sell.owner.shares -= trade_qty
#                             best_sell.owner.trade_count += trade_qty

#                         best_sell.quantity -= trade_qty
#                         remaining_qty -= trade_qty
#                         aggregated_qty += trade_qty
#                         execution_count += 1

#                         network.send_trade(
#                             buy_id=incoming_order.id,
#                             sell_id=best_sell.id,
#                             trade_price=trade_price,
#                             trade_qty=trade_qty
#                         )
#                         self._send_trade_confirmation(incoming_order, best_sell, trade_qty, trade_price)
#                         self.trade_logger.info(
#                             f"T: Trade executed: Buyer Order id {incoming_order.id} and Seller Order id {best_sell.id} "
#                             f"for {trade_qty} units at Rs {trade_price:.2f}. LTP={self.last_traded_price:.2f}"
#                         )
#                         self.last_traded_price = trade_price

#                         if trade_price <= self.daily_lower_bound or trade_price >= self.daily_upper_bound:
#                             if not self.circuit_active:
#                                 self.log.info(
#                                     "Circuit breaker triggered: Trade executed at circuit limit. Halting trading temporarily."
#                                 )
#                                 trigger_circuit_breaker(self)
#                                 self.expand_daily_band()
#                         if best_sell.quantity == 0:
#                             self.order_book.remove_order(best_sell.id)
#                         else:
#                             break
#                     # End inner loop.
#                 if execution_count > 1 and aggregated_qty > 0:
#                     self.trade_logger.info(
#                         f"T: Aggregated Trade: Incoming BUY order id {incoming_order.id} executed "
#                         f"{execution_count} times for total {aggregated_qty} units."
#                     )
#                 if remaining_qty > 0:
#                     incoming_order.quantity = remaining_qty
#                     self.order_book.add_existing_order(incoming_order)
#                     return incoming_order
#                 else:
#                     return None

#             else:  # Sell side.
#                 while remaining_qty > 0:
#                     best_bid_price, total_bid_qty = self.order_book.get_best_bid()
#                     if best_bid_price is None or best_bid_price < limit_price:
#                         break
#                     buy_queue = self.order_book.bids[best_bid_price]
#                     while remaining_qty > 0 and buy_queue:
#                         best_buy = buy_queue[0]
#                         trade_qty = min(remaining_qty, best_buy.quantity)
#                         trade_price = best_bid_price
#                         if incoming_order.owner is not None:
#                             slippage_percent = config.CLIENT_SLIPPAGE_PERCENT
#                         else:
#                             slippage_percent = config.BOT_SLIPPAGE_PERCENT
                        
#                         delta = slippage_percent / 100 * trade_price
#                         slippage = random.uniform(-delta/2, delta/2)
#                         trade_price = enforce_tick(trade_price - slippage)
                        
#                         if total_bid_qty > 0:
#                             extra_impact = config.MARKET_IMPACT_COEFFICIENT * (trade_qty / total_bid_qty) * trade_price
#                             trade_price = enforce_tick(trade_price - extra_impact)

#                         if incoming_order.owner is not None and best_buy.owner is not None:
#                             cost = trade_price * trade_qty
#                             best_buy.owner.cash -= cost
#                             best_buy.owner.shares += trade_qty
#                             best_buy.owner.trade_count += trade_qty
#                             incoming_order.owner.cash += cost
#                             incoming_order.owner.shares -= trade_qty
#                             incoming_order.owner.trade_count += trade_qty

#                         best_buy.quantity -= trade_qty
#                         remaining_qty -= trade_qty
#                         aggregated_qty += trade_qty
#                         execution_count += 1

#                         network.send_trade(
#                             buy_id=best_buy.id,
#                             sell_id=incoming_order.id,
#                             trade_price=trade_price,
#                             trade_qty=trade_qty
#                         )
#                         self._send_trade_confirmation(best_buy, incoming_order, trade_qty, trade_price)
#                         self.trade_logger.info(
#                             f"T: Trade executed: Seller Order id {incoming_order.id} and Buyer Order id {best_buy.id} "
#                             f"for {trade_qty} units at Rs {trade_price:.2f}. LTP={self.last_traded_price:.2f}"
#                         )
#                         self.last_traded_price = trade_price

#                         if trade_price <= self.daily_lower_bound or trade_price >= self.daily_upper_bound:
#                             if not self.circuit_active:
#                                 self.log.info(
#                                     "Circuit breaker triggered: Trade executed at circuit limit. Halting trading temporarily."
#                                 )
#                                 self.circuit_active = True
#                                 self.circuit_trigger_time = time.perf_counter()
#                                 self.expand_daily_band()
#                         if best_buy.quantity == 0:
#                             self.order_book.remove_order(best_buy.id)
#                         else:
#                             break
#                     # End inner loop.
#                 if execution_count > 1 and aggregated_qty > 0:
#                     self.trade_logger.info(
#                         f"T: Aggregated Trade: Incoming SELL order id {incoming_order.id} executed "
#                         f"{execution_count} times for total {aggregated_qty} units."
#                     )
#                 if remaining_qty > 0:
#                     incoming_order.quantity = remaining_qty
#                     self.order_book.add_existing_order(incoming_order)
#                     return incoming_order
#                 else:
#                     return None

#     def _send_trade_confirmation(self, buy_order, sell_order, quantity, price):
#         # Preserve the original log format for extraction.
#         if buy_order.owner is not None:
#             if hasattr(buy_order.owner, "sendall"):
#                 try:
#                     buy_order.owner.sendall(f"TRADE CONFIRM: Bought {quantity} @ {price:.2f}\n".encode())
#                 except Exception as e:
#                     self.log.error(f"Error sending trade confirmation to buyer: {e}")
#             else:
#                 self.log.info(f"TRADE CONFIRM: Bought {quantity} @ {price:.2f}")
#         if sell_order.owner is not None:
#             if hasattr(sell_order.owner, "sendall"):
#                 try:
#                     sell_order.owner.sendall(f"TRADE CONFIRM: Sold {quantity} @ {price:.2f}\n".encode())
#                 except Exception as e:
#                     self.log.error(f"Error sending trade confirmation to seller: {e}")
#             else:
#                 self.log.info(f"TRADE CONFIRM: Sold {quantity} @ {price:.2f}")
