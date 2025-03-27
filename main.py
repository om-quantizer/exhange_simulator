# main.py
import time
import threading
import logging
import os
import random
import datetime

from order_book import OrderBook
from matching_engine import MatchingEngine
# from market_data import MarketData  # (not used now)
from bot_trader import BotTrader
from client_handler import ClientHandler
import config
from trade_profile import AGGRESSIVE_BUYER, AGGRESSIVE_SELLER, PASSIVE, MARKET_MAKER, \
    CONTRARIAN_BUYER, CONTRARIAN_SELLER, MOMENTUM_TRADER, RISK_AVERSE, HIGH_FREQUENCY, TREND_REVERSAL_TRADER

from utils import enforce_tick
from order_book import Order  # Import Order class directly for pre-market insertion

# Define a custom logging Formatter that prints timestamps with microsecond precision.
class MicrosecondFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        ct = datetime.datetime.fromtimestamp(record.created)
        if datefmt:
            s = ct.strftime(datefmt)
        else:
            # Display microseconds with six digits.
            s = ct.strftime("%Y-%m-%d %H:%M:%S.%f")
        return s
    

def snapshot_thread(order_book, interval=1, depth=10):
    """
    Periodically log the order book snapshot every 'interval' seconds,
    capturing the top 'depth' price levels on both sides.
    """
    while True:
        order_book.log_snapshot(depth=depth)  # You must have this method in order_book.py
        order_book.log_best_prices()
        time.sleep(interval)

    
# Set up logging handlers.
if not os.path.exists("logs"):
    os.makedirs("logs")

# Create a file handler and a stream handler.
file_handler = logging.FileHandler("logs/exchange.log", mode="w")
stream_handler = logging.StreamHandler()

# Create our custom formatter.
formatter = MicrosecondFormatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)

# Configure logging with our handlers.
logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])
logger = logging.getLogger("exchange")
logger.info("Starting Multi-Day Exchange Simulator...")

# Set up separate "orderbook" logger -> logs/order_book.log
lob_logger = logging.getLogger("orderbook")
lob_logger.setLevel(logging.INFO)
lob_file_handler = logging.FileHandler("logs/order_book.log", mode="w")
lob_file_handler.setFormatter(formatter)
lob_logger.addHandler(lob_file_handler)

def pre_market_population(order_book, market_price, duration, num_bots=100):
    """
    For a short period (duration seconds), populate the order book with num_bots orders
    placed near the market_price. These orders are added directly (bypassing matching and network calls)
    and no logs will be generated during this period.
    """
    # Temporarily disable logging for the order book and exchange.
    orderbook_logger = logging.getLogger("orderbook")
    exchange_logger = logging.getLogger("exchange")
    old_orderbook_level = orderbook_logger.level
    old_exchange_level = exchange_logger.level
    orderbook_logger.setLevel(logging.CRITICAL)
    exchange_logger.setLevel(logging.CRITICAL)
    
    start_time = time.perf_counter()
    # while time.perf_counter() - start_time < duration:
    for _ in range(50):
        side = random.choice(["B", "S"])
        price_offset = random.uniform(-0.05, 0.05)
        price = enforce_tick(market_price + price_offset)
        qty = random.randint(config.MIN_ORDER_QTY, config.MAX_ORDER_QTY)
        order = Order(side, price, qty)
        # Directly add to order book without network broadcasting.
        order_book._add_to_book(order)
        # time.sleep(0.1)  # Small pause to reduce CPU usage
    # Restore original logging levels.
    orderbook_logger.setLevel(old_orderbook_level)
    exchange_logger.setLevel(old_exchange_level)

def run_simulation_day(engine, day_index, open_price):
    engine.reset_for_new_day(open_price)

    # --- Launch a news shock thread to potentially trigger a shock at a random time during the day ---
    def news_shock_event(engine, day_duration):
        # Wait for a random time between 0 and day_duration seconds
        shock_time = random.uniform(0, day_duration)
        time.sleep(shock_time)
        # With a probability, trigger a news shock event
        if random.random() < config.NEWS_SHOCK_PROB:
            shock_direction = random.choice([-1, 1])
            shock_pct = random.uniform(config.MIN_SHOCK_PERCENT, config.MAX_SHOCK_PERCENT)
            # Apply shock to the current market price (last traded price)
            new_price = engine.last_traded_price * (1 + shock_direction * shock_pct / 100)
            engine.last_traded_price = new_price
            logger.info(f"NEWS SHOCK: Mid-day shock event adjusted market price to {new_price:.2f} "
                        f"(shock: {shock_direction * shock_pct:.2f}%).")
    
    shock_thread = threading.Thread(target=news_shock_event, args=(engine, config.SEC_PER_DAY), daemon=True)
    shock_thread.start()



    bots = []
    profiles = [AGGRESSIVE_BUYER, AGGRESSIVE_SELLER, PASSIVE, MARKET_MAKER,
                CONTRARIAN_BUYER, CONTRARIAN_SELLER, MOMENTUM_TRADER, RISK_AVERSE, HIGH_FREQUENCY, TREND_REVERSAL_TRADER]
    
    weights = [0.15, 0.15, 0.10, 0.10, 0.05, 0.05, 0.15, 0.05, 0.10, 0.10]  # sum = 1.0

    profile = random.choices(profiles, weights=weights, k=1)[0]
    # For demonstration, create new bots each day.
    for i in range(config.NUM_BOTS):
        profile = random.choice(profiles)
        # Bots can still have their own drift/volatility:
        mu = random.uniform(*config.GBM_DRIFT_RANGE)
        sigma = random.uniform(*config.GBM_VOLATILITY_RANGE)
        bot = BotTrader(
            bot_id=i,
            engine=engine,
            profile=profile,
            mu=mu,
            sigma=sigma
        )
        bots.append(bot)
    
    bot_threads = []
    day_duration = config.SEC_PER_DAY  # seconds
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

    # Start the snapshot thread that logs the order book every 5 seconds, top 10 levels
    snap_thread = threading.Thread(
        target=snapshot_thread, args=(order_book, 1, 10), daemon=True
    )
    snap_thread.start()


    #  # ---------------- Pre-Market Warm-Up Phase ----------------
    # current_open = config.INITIAL_PRICE
    # logger.info("Pre-market warm-up phase: Populating order book with marker orders...")
    # pre_market_population(order_book, current_open, config.PRE_MARKET_DURATION, num_bots=100)
    # logger.info("Pre-market warm-up completed. Resetting market parameters for official simulation.")
    
    # # Reset the engine parameters before starting the official market.
    # engine.reset_for_new_day(current_open)

    current_open = config.INITIAL_PRICE
    for day in range(1, config.NUM_DAYS + 1):
        logger.info(f"===== DAY {day} START =====")
        close_price = run_simulation_day(engine, day, current_open)
        if day < config.NUM_DAYS:
            # Compute next day's open using overnight gap
            gap_direction = random.choice([-1, 1])
            # Generate a gap percentage that is at least the minimum and up to the maximum.
            gap_pct = gap_direction * random.uniform(config.MIN_OVERNIGHT_GAP_PERCENT, config.OVERNIGHT_GAP_PERCENT)
            next_open = close_price * (1 + gap_pct/100)
            current_open = next_open
            logger.info(f"Overnight gap: Day {day} close = {close_price:.2f}, Day {day+1} open = {current_open:.2f}")
    
    logger.info("Simulation complete. Shutting down.")
