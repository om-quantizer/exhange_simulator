# main.py
# Entry point for the Multi-Day Exchange Simulator.
# Sets up logging, threads, and orchestrates the daily trading cycle.

import time                  # For sleep intervals and timestamps
import threading             # To run concurrent tasks for bots, snapshots, etc.
import logging               # For logging system events to console and files
import os                    # For filesystem operations (e.g., creating logs directory)
import random                # To introduce stochastic behaviors (bot profiles, shocks)
import datetime              # To format timestamps with microsecond precision

from order_book import OrderBook              # Core in-memory LOB data structure
from matching_engine import MatchingEngine    # Main matching engine handling order execution
from bot_trader import BotTrader              # Bot trader class simulating algorithmic agents
from client_handler import ClientHandler      # TCP server for client order interaction
import config                                 # Global configuration parameters
from trade_profile import (                    
    AGGRESSIVE_BUYER,           # Profile: large fast bids
    AGGRESSIVE_SELLER,          # Profile: large fast asks
    PASSIVE,                    # Profile: minimal directional pressure
    MARKET_MAKER,               # Profile: capturing spread
    CONTRARIAN_BUYER,           # Profile: buys on dips
    CONTRARIAN_SELLER,          # Profile: sells on rallies
    MOMENTUM_TRADER,            # Profile: follows current trend
    RISK_AVERSE,                # Profile: small slow orders
    HIGH_FREQUENCY,             # Profile: rapid-fire micro orders
    TREND_REVERSAL_TRADER       # Profile: trades against short-term trend
)
from utils import enforce_tick                   # Rounds prices to tick grid
from order_book import Order                    # Order class with unique IDs and state

# Custom log formatter including microsecond resolution
class MicrosecondFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        # Convert record.created (seconds) to datetime with fractional seconds
        ct = datetime.datetime.fromtimestamp(record.created)
        if datefmt:
            s = ct.strftime(datefmt)            # Use provided format string
        else:
            s = ct.strftime("%Y-%m-%d %H:%M:%S.%f")  # Default: ISO-like with microseconds
        return s

# Thread target for periodic LOB snapshots and best-price logging
def snapshot_thread(order_book, interval=1, depth=10):
    """
    Logs full LOB depth and best prices periodically.

    Args:
        order_book: shared OrderBook instance
        interval: sleep duration between snapshots (sec)
        depth: number of price levels to include per side
    """
    while True:                                # Repeat indefinitely
        order_book.log_snapshot(depth=depth)   # Log top N levels
        order_book.log_best_prices()           # Log current bid/ask
        time.sleep(interval)                   # Pause before next snapshot

# Thread to spawn extra momentum bots based on volatility threshold
def additional_bot_monitor(engine, bots, day_end_time, spawn_lock):
    last_spawn_time = 0                        # Timestamp of last spawn to enforce cooldown
    while time.time() < day_end_time:          # While trading day still active
        # Compute volatility ratio relative to daily open
        current_volatility = abs(engine.last_traded_price - engine.daily_open_price) / engine.daily_open_price
        if current_volatility > config.DYNAMIC_BOT_SPAWN_THRESHOLD:
            if time.time() - last_spawn_time > config.DYNAMIC_BOT_SPAWN_COOLDOWN:
                with spawn_lock:                # Ensure only one spawn at a time
                    bot_id = len(bots)         # New bot index
                    # Create momentum trader bot
                    new_bot = BotTrader(
                        bot_id,
                        engine,
                        profile=MOMENTUM_TRADER,
                        mu=random.uniform(*MOMENTUM_TRADER.mu_range),
                        sigma=random.uniform(*MOMENTUM_TRADER.sigma_range)
                    )
                    bots.append(new_bot)       # Register in bot list
                    # Start bot thread for full-day duration
                    t = threading.Thread(
                        target=new_bot.run,
                        kwargs={"duration": config.SEC_PER_DAY},
                        daemon=True
                    )
                    t.start()
                    logging.getLogger("exchange").info(
                        f"Dynamic Spawn: New Momentum Trader Bot {bot_id} spawned due to high volatility."
                    )
                    last_spawn_time = time.time()  # Reset spawn cooldown
        time.sleep(0.5)  # Check twice per second

# Ensure 'logs' directory exists for file handlers
if not os.path.exists("logs"):
    os.makedirs("logs")                    # Creates directory if missing

# Configure file and console logging with microsecond timestamps
file_handler = logging.FileHandler("logs/exchange.log", mode="w")  # Overwrite each run
stream_handler = logging.StreamHandler()
formatter = MicrosecondFormatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)
logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])
logger = logging.getLogger("exchange")
logger.info("Starting Multi-Day Exchange Simulator...")  # Initial log entry

# Dedicated logger for orderbook snapshots
lob_logger = logging.getLogger("orderbook")
lob_logger.setLevel(logging.INFO)
lob_file_handler = logging.FileHandler("logs/order_book.log", mode="w")
lob_file_handler.setFormatter(formatter)
lob_logger.addHandler(lob_file_handler)

# Periodic fundamental value updater (unused in this version)
def fundamental_updater(engine, update_interval=1):
    while True:
        engine.update_fundamental(update_interval)
        time.sleep(update_interval)

# Random news shock injected mid-day to simulate external events
def news_shock_event(engine, day_duration):
    shock_time = random.uniform(0, day_duration)  # Uniform random within day
    time.sleep(shock_time)
    if random.random() < config.NEWS_SHOCK_PROB:  # Probability check
        shock_direction = random.choice([-1, 1])  # Up or down
        shock_pct = random.uniform(config.MIN_SHOCK_PERCENT, config.MAX_SHOCK_PERCENT)
        shock_order_qty = 10                        # Size for shock
        # Execute large market order at best price
        if shock_direction > 0:
            best_ask, _ = engine.order_book.get_best_ask() or (engine.last_traded_price, None)
            engine.process_order("B", best_ask, shock_order_qty)
        else:
            best_bid, _ = engine.order_book.get_best_bid() or (engine.last_traded_price, None)
            engine.process_order("S", best_bid, shock_order_qty)
        new_price = engine.last_traded_price * (1 + shock_direction * shock_pct / 100)
        engine.last_traded_price = new_price       # Force adjust last traded price
        logger.info(
            f"NEWS SHOCK: Adjusted LTP to {new_price:.2f} (shock: {shock_direction * shock_pct:.2f}%)."
        )
        engine.expand_daily_band()                  # Expand circuit boundaries

# Define available trader profiles for simulation
profiles = [
    AGGRESSIVE_BUYER, AGGRESSIVE_SELLER, PASSIVE, MARKET_MAKER,
    CONTRARIAN_BUYER, CONTRARIAN_SELLER, MOMENTUM_TRADER,
    RISK_AVERSE, HIGH_FREQUENCY, TREND_REVERSAL_TRADER
]
# Base weights controlling initial mix of profiles
base_weights = [0.10, 0.10, 0.10, 0.15, 0.10, 0.10, 0.30, 0.10, 0.10, 0.10]

# Core function to simulate one "day" of trading
def run_simulation_day(engine, day_index, open_price):
    engine.reset_for_new_day(open_price)         # Reset daily LOB and engine state
    bots = []                                    # Collect BotTrader instances
    engine.base_weights = base_weights           # Set base weights in engine
    engine.profiles = profiles                   # Profiles available for dynamic updates
    # Randomize weights slightly for heterogeneity
    dynamic_weights = [max(0, w + random.uniform(-0.05, 0.05)) for w in base_weights]
    total = sum(dynamic_weights)
    normalized_weights = [w / total for w in dynamic_weights]
    # Instantiate configured number of bots
    for i in range(config.NUM_BOTS):
        profile = random.choices(profiles, weights=normalized_weights, k=1)[0]
        mu = random.uniform(*profile.mu_range)
        sigma = random.uniform(*profile.sigma_range)
        bots.append(BotTrader(i, engine, profile, mu, sigma))
    # Start dynamic bot monitor thread
    day_end_time = time.time() + config.SEC_PER_DAY
    spawn_lock = threading.Lock()
    threading.Thread(
        target=additional_bot_monitor,
        args=(engine, bots, day_end_time, spawn_lock),
        daemon=True
    ).start()
    # Start news shock thread
    threading.Thread(
        target=news_shock_event,
        args=(engine, config.SEC_PER_DAY),
        daemon=True
    ).start()
    # Launch each bot's run() in its own thread
    threads = []
    for bot in bots:
        t = threading.Thread(target=bot.run, kwargs={"duration": config.SEC_PER_DAY}, daemon=True)
        t.start()
        threads.append(t)
    for t in threads: t.join()                  # Wait for all bots to finish
    close_price = engine.last_traded_price      # Capture end-of-day price
    logging.getLogger("exchange").info(f"Day {day_index} ended. Close price = {close_price:.2f}")
    return close_price

# Main guard to start simulation when executed as script
if __name__ == "__main__":
    order_book = OrderBook()                    # Shared LOB structure
    engine = MatchingEngine(order_book)         # Matching engine instance
    client_handler = ClientHandler(engine)      # TCP server for clients
    threading.Thread(target=client_handler.start, daemon=True).start()  # Start client listener
    # Kick off periodic LOB snapshots
    threading.Thread(
        target=snapshot_thread,
        args=(order_book, config.TICK_INTERVAL, 10),
        daemon=True
    ).start()
    current_open = config.INITIAL_PRICE         # Starting price for day 1
    for day in range(1, config.NUM_DAYS + 1):
        logger.info(f"===== DAY {day} START =====")
        close = run_simulation_day(engine, day, current_open)
        if day < config.NUM_DAYS:
            # Compute random overnight gap for next day's open
            gap = random.choice([-1,1]) * random.uniform(
                config.MIN_OVERNIGHT_GAP_PERCENT,
                config.OVERNIGHT_GAP_PERCENT
            )
            current_open = close * (1 + gap/100)
            logger.info(
                f"Overnight gap: Day {day} close={close:.2f}, next open={current_open:.2f}"
            )
    logger.info("Simulation complete. Shutting down.")


# import time
# import threading
# import logging
# import os
# import random
# import datetime

# from order_book import OrderBook
# from matching_engine import MatchingEngine
# from bot_trader import BotTrader
# from client_handler import ClientHandler  # Assuming this file exists.
# import config
# from trade_profile import AGGRESSIVE_BUYER, AGGRESSIVE_SELLER, PASSIVE, MARKET_MAKER, \
#     CONTRARIAN_BUYER, CONTRARIAN_SELLER, MOMENTUM_TRADER, RISK_AVERSE, HIGH_FREQUENCY, \
#     TREND_REVERSAL_TRADER, INVESTOR
# from utils import enforce_tick
# from order_book import Order

# class MicrosecondFormatter(logging.Formatter):
#     def formatTime(self, record, datefmt=None):
#         ct = datetime.datetime.fromtimestamp(record.created)
#         return ct.strftime(datefmt if datefmt else "%Y-%m-%d %H:%M:%S.%f")

# def snapshot_thread(order_book, interval=1, depth=10):
#     while True:
#         order_book.log_snapshot(depth=depth)
#         order_book.log_best_prices()
#         time.sleep(interval)

# def portfolio_snapshot_thread(bots, total_duration):
#     """
#     Takes exactly 6 snapshots evenly spaced over the total_duration.
#     Each snapshot logs every bot's information (ID, profile, trade count,
#     available cash, shares, and total portfolio value).
#     """
#     snapshot_interval = total_duration / 6.0  # Capture 6 snapshots per day.
#     portfolio_logger = logging.getLogger("portfolio")
#     for i in range(6):
#         timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
#         for bot in bots:
#             current_price = bot.engine.last_traded_price if bot.engine.last_traded_price else config.INITIAL_PRICE
#             total_value = bot.cash + bot.shares * current_price
#             portfolio_logger.info(
#                 f"PORTFOLIO_SNAPSHOT,{timestamp_str},BotID={bot.bot_id},Profile={bot.profile.name},"
#                 f"Trades={bot.trade_count},Cash={bot.cash:.2f},Shares={bot.shares},Value={total_value:.2f}"
#             )
#         time.sleep(snapshot_interval)

# def additional_bot_monitor(engine, bots, day_end_time, spawn_lock):
#     last_spawn_time = 0
#     while time.time() < day_end_time:
#         current_volatility = abs(engine.last_traded_price - engine.daily_open_price) / engine.daily_open_price
#         if current_volatility > config.DYNAMIC_BOT_SPAWN_THRESHOLD:
#             if time.time() - last_spawn_time > config.DYNAMIC_BOT_SPAWN_COOLDOWN:
#                 bot_id = len(bots)
#                 # For dynamic spawning, we use a Momentum Trader here.
#                 new_bot = BotTrader(bot_id, engine, profile=MOMENTUM_TRADER,
#                                     mu=random.uniform(*MOMENTUM_TRADER.mu_range),
#                                     sigma=random.uniform(*MOMENTUM_TRADER.sigma_range))
#                 bots.append(new_bot)
#                 t = threading.Thread(target=new_bot.run, kwargs={"duration": config.SEC_PER_DAY}, daemon=True)
#                 t.start()
#                 logging.getLogger("exchange").info(f"Dynamic Spawn: New Momentum Trader Bot {bot_id} spawned due to high volatility.")
#                 last_spawn_time = time.time()
#         time.sleep(0.5)

# if not os.path.exists("logs"):
#     os.makedirs("logs")

# # Setup loggers.
# file_handler = logging.FileHandler("logs/exchange.log", mode="w")
# stream_handler = logging.StreamHandler()
# formatter = MicrosecondFormatter("%(asctime)s [%(levelname)s] %(message)s")
# file_handler.setFormatter(formatter)
# stream_handler.setFormatter(formatter)
# logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])
# logger = logging.getLogger("exchange")
# logger.info("Starting Multi-Day Exchange Simulator...")

# lob_logger = logging.getLogger("orderbook")
# lob_logger.setLevel(logging.INFO)
# lob_file_handler = logging.FileHandler("logs/order_book.log", mode="w")
# lob_file_handler.setFormatter(formatter)
# lob_logger.addHandler(lob_file_handler)

# # Setup portfolio logger.
# portfolio_logger = logging.getLogger("portfolio")
# portfolio_logger.setLevel(logging.INFO)
# portfolio_file_handler = logging.FileHandler("logs/portfolio.log", mode="w")
# portfolio_file_handler.setFormatter(formatter)
# portfolio_logger.addHandler(portfolio_file_handler)

# def fundamental_updater(engine, update_interval=1):
#     while True:
#         engine.update_fundamental(update_interval)
#         time.sleep(update_interval)

# def news_shock_event(engine, day_duration):
#     shock_time = random.uniform(0, day_duration)
#     time.sleep(shock_time)
#     if random.random() < config.NEWS_SHOCK_PROB:
#         shock_direction = random.choice([-1, 1])
#         shock_pct = random.uniform(config.MIN_SHOCK_PERCENT, config.MAX_SHOCK_PERCENT)
#         shock_order_qty = 10  # Large order quantity for shock.
#         if shock_direction > 0:
#             best_ask, _ = engine.order_book.get_best_ask()
#             best_ask = best_ask or engine.last_traded_price
#             engine.process_order("B", best_ask, shock_order_qty)
#         else:
#             best_bid, _ = engine.order_book.get_best_bid()
#             best_bid = best_bid or engine.last_traded_price
#             engine.process_order("S", best_bid, shock_order_qty)
#         new_price = engine.last_traded_price * (1 + shock_direction * shock_pct / 100)
#         engine.last_traded_price = new_price
#         logger.info(f"NEWS SHOCK: Adjusted LTP to {new_price:.2f} (shock: {shock_direction * shock_pct:.2f}%).")
#         engine.expand_daily_band()

# # Updated profiles list now includes the INVESTOR profile.
# profiles = [AGGRESSIVE_BUYER, AGGRESSIVE_SELLER, PASSIVE, MARKET_MAKER,
#             CONTRARIAN_BUYER, CONTRARIAN_SELLER, MOMENTUM_TRADER, RISK_AVERSE,
#             HIGH_FREQUENCY, TREND_REVERSAL_TRADER, INVESTOR]

# # Adjust base weights for 11 profiles. (Weights can be tuned as needed.)
# base_weights = [0.10, 0.10, 0.10, 0.15, 0.10, 0.10, 0.50, 0.10, 0.10, 0.10, 0.10]

# def run_simulation_day(engine, day_index, open_price):
#     engine.reset_for_new_day(open_price)
#     bots = []

#     engine.base_weights = base_weights
#     engine.profiles = profiles

#     dynamic_weights = [max(0, w + random.uniform(-0.05, 0.05)) for w in base_weights]
#     total = sum(dynamic_weights)
#     normalized_weights = [w / total for w in dynamic_weights]

#     for i in range(config.NUM_BOTS):
#         profile = random.choices(profiles, weights=normalized_weights, k=1)[0]
#         mu = random.uniform(*profile.mu_range)
#         sigma = random.uniform(*profile.sigma_range)
#         bot = BotTrader(bot_id=i, engine=engine, profile=profile, mu=mu, sigma=sigma)
#         bots.append(bot)

#     # Start portfolio snapshot thread.
#     portfolio_thread = threading.Thread(target=portfolio_snapshot_thread, args=(bots, config.SEC_PER_DAY))
#     portfolio_thread.start()

#     day_end_time = time.time() + config.SEC_PER_DAY
#     spawn_lock = threading.Lock()
#     monitor_thread = threading.Thread(target=additional_bot_monitor, args=(engine, bots, day_end_time, spawn_lock), daemon=True)
#     monitor_thread.start()

#     shock_thread = threading.Thread(target=news_shock_event, args=(engine, config.SEC_PER_DAY), daemon=True)
#     shock_thread.start()

#     bot_threads = []
#     for bot in bots:
#         t = threading.Thread(target=bot.run, kwargs={"duration": config.SEC_PER_DAY}, daemon=True)
#         t.start()
#         bot_threads.append(t)
    
#     for t in bot_threads:
#         t.join()
    
#     close_price = engine.last_traded_price
#     logging.getLogger("exchange").info(f"Day {day_index} ended. Close price = {close_price:.2f}")
#     return close_price

# if __name__ == "__main__":
#     order_book = OrderBook()
#     engine = MatchingEngine(order_book)
#     client_handler = ClientHandler(engine)
    
#     client_thread = threading.Thread(target=client_handler.start, daemon=True)
#     client_thread.start()

#     snap_thread = threading.Thread(target=snapshot_thread, args=(order_book, config.TICK_INTERVAL, 10), daemon=True)
#     snap_thread.start()

#     current_open = config.INITIAL_PRICE
#     for day in range(1, config.NUM_DAYS + 1):
#         logger.info(f"===== DAY {day} START =====")
#         close_price = run_simulation_day(engine, day, current_open)
#         if day < config.NUM_DAYS:
#             gap_direction = random.choice([-1, 1])
#             gap_pct = gap_direction * random.uniform(config.MIN_OVERNIGHT_GAP_PERCENT, config.OVERNIGHT_GAP_PERCENT)
#             next_open = close_price * (1 + gap_pct/100)
#             current_open = next_open
#             logger.info(f"Overnight gap: Day {day} close = {close_price:.2f}, Day {day+1} open = {current_open:.2f}")
    
#     logger.info("Simulation complete. Shutting down.")
