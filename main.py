# main.py
import time
import threading
import logging
import os
import random
import datetime

from order_book import OrderBook
from matching_engine import MatchingEngine
from bot_trader import BotTrader
from client_handler import ClientHandler
import config
from trade_profile import AGGRESSIVE_BUYER, AGGRESSIVE_SELLER, PASSIVE, MARKET_MAKER, \
    CONTRARIAN_BUYER, CONTRARIAN_SELLER, MOMENTUM_TRADER, RISK_AVERSE, HIGH_FREQUENCY, TREND_REVERSAL_TRADER
from utils import enforce_tick
from order_book import Order

class MicrosecondFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        ct = datetime.datetime.fromtimestamp(record.created)
        if datefmt:
            s = ct.strftime(datefmt)
        else:
            s = ct.strftime("%Y-%m-%d %H:%M:%S.%f")
        return s
    

def snapshot_thread(order_book, interval=1, depth=10):
    while True:
        order_book.log_snapshot(depth=depth)
        order_book.log_best_prices()
        time.sleep(interval)

if not os.path.exists("logs"):
    os.makedirs("logs")

file_handler = logging.FileHandler("logs/exchange.log", mode="w")
stream_handler = logging.StreamHandler()
formatter = MicrosecondFormatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)
logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])
logger = logging.getLogger("exchange")
logger.info("Starting Multi-Day Exchange Simulator...")

lob_logger = logging.getLogger("orderbook")
lob_logger.setLevel(logging.INFO)
lob_file_handler = logging.FileHandler("logs/order_book.log", mode="w")
lob_file_handler.setFormatter(formatter)
lob_logger.addHandler(lob_file_handler)

# def pre_market_population(order_book, market_price, duration, num_bots=100):
#     orderbook_logger = logging.getLogger("orderbook")
#     exchange_logger = logging.getLogger("exchange")
#     old_orderbook_level = orderbook_logger.level
#     old_exchange_level = exchange_logger.level
#     orderbook_logger.setLevel(logging.CRITICAL)
#     exchange_logger.setLevel(logging.CRITICAL)
    
#     start_time = time.perf_counter()
#     for _ in range(50):
#         side = random.choice(["B", "S"])
#         price_offset = random.uniform(-0.05, 0.05)
#         price = enforce_tick(market_price + price_offset)
#         qty = random.randint(config.MIN_ORDER_QTY, config.MAX_ORDER_QTY)
#         order = Order(side, price, qty)
#         order_book._add_to_book(order)
#     orderbook_logger.setLevel(old_orderbook_level)
#     exchange_logger.setLevel(old_exchange_level)

def fundamental_updater(engine, update_interval=1):
    while True:
        engine.update_fundamental(update_interval)
        time.sleep(update_interval)

def news_shock_event(engine, day_duration):
    shock_time = random.uniform(0, day_duration)
    time.sleep(shock_time)
    if random.random() < config.NEWS_SHOCK_PROB:
        shock_direction = random.choice([-1, 1])
        shock_pct = random.uniform(config.MIN_SHOCK_PERCENT, config.MAX_SHOCK_PERCENT)
        # Simulate shock via a large market order:
        shock_order_qty = 10  # Large order quantity for shock effect
        if shock_direction > 0:
            best_ask, _ = engine.order_book.get_best_ask()
            if best_ask is None:
                best_ask = engine.last_traded_price
            engine.process_order("B", best_ask, shock_order_qty)
        else:
            best_bid, _ = engine.order_book.get_best_bid()
            if best_bid is None:
                best_bid = engine.last_traded_price
            engine.process_order("S", best_bid, shock_order_qty)
        new_price = engine.last_traded_price * (1 + shock_direction * shock_pct / 100)
        engine.last_traded_price = new_price
        logger.info(f"NEWS SHOCK: Adjusted LTP to {new_price:.2f} (shock: {shock_direction * shock_pct:.2f}%).")
        engine.expand_daily_band()

profiles = [AGGRESSIVE_BUYER, AGGRESSIVE_SELLER, PASSIVE, MARKET_MAKER,
            CONTRARIAN_BUYER, CONTRARIAN_SELLER, MOMENTUM_TRADER, RISK_AVERSE, HIGH_FREQUENCY, TREND_REVERSAL_TRADER]

base_weights = [0.10, 0.10, 0.10, 0.15, 0.10, 0.10, 0.50, 0.10, 0.10, 0.10]  # Adjust weights as desired

def run_simulation_day(engine, day_index, open_price):
    engine.reset_for_new_day(open_price)
    bots = []

    # Store the base weights and profiles in the engine (they remain static over the day)
    engine.base_weights = base_weights
    engine.profiles = profiles

    # (Optionally, you can also update the weights dynamically at the beginning of the day)
    # For each bot, choose a profile using dynamic weights computed at initialization:
    dynamic_weights = [max(0, w + random.uniform(-0.05, 0.05)) for w in base_weights]
    total = sum(dynamic_weights)
    normalized_weights = [w / total for w in dynamic_weights]

    # # weights = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1]  # Adjust weights as desired

    # profiles = [TREND_REVERSAL_TRADER]
    
    # weights = [1]  # Adjust weights as desired


    profile = random.choices(profiles, weights=normalized_weights, k=1)[0]

    for i in range(config.NUM_BOTS):
        profile = random.choice(profiles)
        mu = random.uniform(*profile.mu_range)
        sigma = random.uniform(*profile.sigma_range)
        bot = BotTrader(
            bot_id=i,
            engine=engine,
            profile=profile,
            mu=mu,
            sigma=sigma
        )
        bots.append(bot)

    # Start news shock thread
    shock_thread = threading.Thread(target=news_shock_event, args=(engine, config.SEC_PER_DAY), daemon=True)
    shock_thread.start()

    bot_threads = []
    day_duration = config.SEC_PER_DAY
    for bot in bots:
        t = threading.Thread(target=bot.run, kwargs={"duration": day_duration}, daemon=True)
        t.start()
        bot_threads.append(t)
    

    for t in bot_threads:
        t.join()
    
    close_price = engine.last_traded_price
    logging.getLogger("exchange").info(f"Day {day_index} ended. Close price = {close_price:.2f}")
    return close_price

if __name__ == "__main__":
    order_book = OrderBook()
    engine = MatchingEngine(order_book)
    client_handler = ClientHandler(engine)
    
    client_thread = threading.Thread(target=client_handler.start, daemon=True)
    client_thread.start()

    snap_thread = threading.Thread(target=snapshot_thread, args=(order_book, 0.1, 10), daemon=True)
    snap_thread.start()

    current_open = config.INITIAL_PRICE
    for day in range(1, config.NUM_DAYS + 1):
        logger.info(f"===== DAY {day} START =====")
        close_price = run_simulation_day(engine, day, current_open)
        if day < config.NUM_DAYS:
            gap_direction = random.choice([-1, 1])
            gap_pct = gap_direction * random.uniform(config.MIN_OVERNIGHT_GAP_PERCENT, config.OVERNIGHT_GAP_PERCENT)
            next_open = close_price * (1 + gap_pct/100)
            current_open = next_open
            logger.info(f"Overnight gap: Day {day} close = {close_price:.2f}, Day {day+1} open = {current_open:.2f}")
    
    logger.info("Simulation complete. Shutting down.")
