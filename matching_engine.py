# matching_engine.py
# Order matching engine with FIFO price-time priority, multi-level matching,
# and enhanced DPR/TER logic including mirror random slippage.

import logging
import threading
import time
import random
import network
from utils import enforce_tick
import config

class MatchingEngine:
    def __init__(self, order_book):
        self.order_book = order_book
        self.log = logging.getLogger("exchange")
        self.trade_logger = logging.getLogger("trade")
        self.last_traded_price = config.INITIAL_PRICE  # Track last traded price (LTP)
        self.lock = threading.Lock()
        # Daily band setup (DPR - Daily Price Range):
        self.daily_open_price = config.INITIAL_PRICE
        self.current_band_percent = config.MAX_DAILY_MOVE_PERCENT
        self.daily_lower_bound = self.daily_open_price * (1 - self.current_band_percent / 100)
        self.daily_upper_bound = self.daily_open_price * (1 + self.current_band_percent / 100)
        
        # Circuit breaker initialization
        self.circuit_active = False
        self.circuit_trigger_time = None

    def reset_for_new_day(self, new_open_price):
        """Reset daily parameters at the start of a new day."""
        with self.lock:
            self.daily_open_price = new_open_price
            self.current_band_percent = config.MAX_DAILY_MOVE_PERCENT
            self.daily_lower_bound = self.daily_open_price * (1 - self.current_band_percent / 100)
            self.daily_upper_bound = self.daily_open_price * (1 + self.current_band_percent / 100)
            # Reset circuit breaker at the start of a new day
            self.circuit_active = False
            self.circuit_trigger_time = None
            self.log.info(f"New day started. Open price={new_open_price:.2f}, Band=±{self.current_band_percent}% "
                          f"({self.daily_lower_bound:.2f} - {self.daily_upper_bound:.2f})")

    def expand_daily_band(self):
        """Expand the daily band by a fixed increment."""
        self.current_band_percent += config.BAND_EXPANSION_INCREMENT
        self.daily_lower_bound = self.daily_open_price * (1 - self.current_band_percent / 100)
        self.daily_upper_bound = self.daily_open_price * (1 + self.current_band_percent / 100)
        self.log.info(f"Daily band expanded to ±{self.current_band_percent}%. New bounds: "
                      f"[{self.daily_lower_bound:.2f}, {self.daily_upper_bound:.2f}]")
        

    def get_market_trend(self):
        """
        Determine the current market trend based on the daily open and the last traded price.
        Returns 'bullish', 'bearish', or 'sideways'.
        """
        threshold = 0.005 * self.daily_open_price  # 0.5% threshold
        if self.last_traded_price > self.daily_open_price + threshold:
            return "bullish"
        elif self.last_traded_price < self.daily_open_price - threshold:
            return "bearish"
        else:
            return "sideways"


    def process_order(self, side, limit_price, quantity, owner=None):
        from order_book import Order
        incoming_order = Order(side, limit_price, quantity, owner)
        
        # Check if circuit breaker is active
        if self.circuit_active:
            if time.perf_counter() - self.circuit_trigger_time < config.CIRCUIT_BREAKER_DURATION:
                self.log.info("Circuit breaker active. Order rejected.")
                network.send_rejection(incoming_order)
                return None
            else:
                # Reset circuit breaker if the halt duration has expired
                self.circuit_active = False
                self.circuit_trigger_time = None

        network.send_order(incoming_order)
        remaining_qty = quantity

        # Clamp the incoming order's limit to the DPR bounds.
        if limit_price < self.daily_lower_bound:
            limit_price = self.daily_lower_bound
        elif limit_price > self.daily_upper_bound:
            limit_price = self.daily_upper_bound
        incoming_order.price = enforce_tick(limit_price)

        # Enforce TER (Trade Execution Range)
        ter_lower_bound = self.daily_open_price * (1 - config.TER_PERCENT / 100)
        ter_upper_bound = self.daily_open_price * (1 + config.TER_PERCENT / 100)
        if limit_price < ter_lower_bound or limit_price > ter_upper_bound:
            self.log.info(
                f"Order price {limit_price:.2f} outside TER range ({ter_lower_bound:.2f}-{ter_upper_bound:.2f}). Order rejected."
            )
            network.send_rejection(incoming_order)
            return None

        aggregated_qty = 0
        execution_count = 0

        with self.lock:
            if side == 'B':
                # Process BUY order: walk through ask levels (lowest ask first)
                while remaining_qty > 0:
                    best_ask_price, total_ask_qty = self.order_book.get_best_ask()
                    if best_ask_price is None or best_ask_price > limit_price:
                        break

                    sell_queue = self.order_book.asks[best_ask_price]
                    while remaining_qty > 0 and sell_queue:
                        best_sell = sell_queue[0]  # FIFO order at this price level
                        trade_qty = min(remaining_qty, best_sell.quantity)
                        # Set initial trade price from best ask price.
                        trade_price = best_ask_price
                        # Apply mirror random slippage:
                        if incoming_order.owner is not None:
                            slippage_percent = config.CLIENT_SLIPPAGE_PERCENT
                        else:
                            slippage_percent = config.BOT_SLIPPAGE_PERCENT
                        slippage = random.uniform(0, slippage_percent/100 * trade_price)
                        trade_price = enforce_tick(trade_price + slippage)

                        best_sell.quantity -= trade_qty
                        remaining_qty -= trade_qty
                        aggregated_qty += trade_qty
                        execution_count += 1

                        network.send_trade(
                            buy_id=incoming_order.id,
                            sell_id=best_sell.id,
                            trade_price=trade_price,
                            trade_qty=trade_qty
                        )
                        self._send_trade_confirmation(incoming_order, best_sell, trade_qty, trade_price)
                        self.trade_logger.info(
                            f"T: Trade executed: Buyer Order id {incoming_order.id} and Seller Order id {best_sell.id} "
                            f"for {trade_qty} units at Rs {trade_price:.2f}. LTP={self.last_traded_price:.2f}"
                        )
                        self.last_traded_price = trade_price

                        if trade_price <= self.daily_lower_bound or trade_price >= self.daily_upper_bound:
                            if not self.circuit_active:
                                self.log.info(
                                    "Circuit breaker triggered: Trade executed at circuit limit. Halting trading temporarily."
                                )
                                self.circuit_active = True
                                self.circuit_trigger_time = time.perf_counter()

                        if best_sell.quantity == 0:
                            self.order_book.remove_order(best_sell.id)
                        else:
                            break
                    # End inner loop.
                # End while loop.

                if execution_count > 1 and aggregated_qty > 0:
                    self.trade_logger.info(
                        f"T: Aggregated Trade: Incoming BUY order id {incoming_order.id} executed "
                        f"{execution_count} times for total {aggregated_qty} units."
                    )

                if remaining_qty > 0:
                    incoming_order.quantity = remaining_qty
                    self.order_book.add_existing_order(incoming_order)
                    return incoming_order
                else:
                    return None

            else:
                # Process SELL order: walk through bid levels (highest bid first)
                while remaining_qty > 0:
                    best_bid_price, total_bid_qty = self.order_book.get_best_bid()
                    if best_bid_price is None or best_bid_price < limit_price:
                        break

                    buy_queue = self.order_book.bids[best_bid_price]
                    while remaining_qty > 0 and buy_queue:
                        best_buy = buy_queue[0]
                        trade_qty = min(remaining_qty, best_buy.quantity)
                        trade_price = best_bid_price
                        # Apply mirror random slippage for sell orders:
                        if incoming_order.owner is not None:
                            slippage_percent = config.CLIENT_SLIPPAGE_PERCENT
                        else:
                            slippage_percent = config.BOT_SLIPPAGE_PERCENT
                        slippage = random.uniform(0, slippage_percent/100 * trade_price)
                        trade_price = enforce_tick(trade_price - slippage)

                        best_buy.quantity -= trade_qty
                        remaining_qty -= trade_qty
                        aggregated_qty += trade_qty
                        execution_count += 1

                        network.send_trade(
                            buy_id=best_buy.id,
                            sell_id=incoming_order.id,
                            trade_price=trade_price,
                            trade_qty=trade_qty
                        )
                        self._send_trade_confirmation(best_buy, incoming_order, trade_qty, trade_price)
                        self.trade_logger.info(
                            f"T: Trade executed: Seller Order id {incoming_order.id} and Buyer Order id {best_buy.id} "
                            f"for {trade_qty} units at Rs {trade_price:.2f}. LTP={self.last_traded_price:.2f}"
                        )
                        self.last_traded_price = trade_price

                        if trade_price <= self.daily_lower_bound or trade_price >= self.daily_upper_bound:
                            if not self.circuit_active:
                                self.log.info(
                                    "Circuit breaker triggered: Trade executed at circuit limit. Halting trading temporarily."
                                )
                                self.circuit_active = True
                                self.circuit_trigger_time = time.perf_counter()

                        if best_buy.quantity == 0:
                            self.order_book.remove_order(best_buy.id)
                        else:
                            break
                    # End inner loop.
                # End while loop.

                if execution_count > 1 and aggregated_qty > 0:
                    self.trade_logger.info(
                        f"T: Aggregated Trade: Incoming SELL order id {incoming_order.id} executed "
                        f"{execution_count} times for total {aggregated_qty} units."
                    )

                if remaining_qty > 0:
                    incoming_order.quantity = remaining_qty
                    self.order_book.add_existing_order(incoming_order)
                    return incoming_order
                else:
                    return None

    def _send_trade_confirmation(self, buy_order, sell_order, quantity, price):
        if buy_order.owner is not None:
            try:
                buy_order.owner.sendall(f"TRADE CONFIRM: Bought {quantity} @ {price:.2f}\n".encode())
            except Exception as e:
                self.log.error(f"Error sending trade confirmation to buyer: {e}")
        if sell_order.owner is not None:
            try:
                sell_order.owner.sendall(f"TRADE CONFIRM: Sold {quantity} @ {price:.2f}\n".encode())
            except Exception as e:
                self.log.error(f"Error sending trade confirmation to seller: {e}")
