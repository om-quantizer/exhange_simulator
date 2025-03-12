# main.py
# Entry point of the exchange simulator.

import time
import logging
import os
import threading

from order_book import OrderBook
from matching_engine import MatchingEngine

from market_data import MarketData
from bot_trader import BotTrader
from client_handler import ClientHandler
import config

if __name__ == "__main__":
    # Create logs directory if it doesn't exist.
    if not os.path.exists("logs"):
        os.makedirs("logs")
    
    # Set up logging to file and console.
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[
                            logging.FileHandler("logs/exchange.log", mode="w"),
                            logging.StreamHandler()
                        ])
    logger = logging.getLogger("exchange")
    logger.info("Starting Exchange Simulator...")

    # Initialize core components.
    order_book = OrderBook()
    engine = MatchingEngine(order_book)
    market_data = MarketData(config.INITIAL_PRICE, config.GBM_DRIFT, config.GBM_VOLATILITY, config.TICK_INTERVAL)
    client_handler = ClientHandler(engine)
    bots = [BotTrader(i, engine, market_data) for i in range(config.NUM_BOTS)]

    # Set a simulation duration (in seconds)
    simulation_duration = 20

    # Start the TCP client handler in a separate thread.
    client_thread = threading.Thread(target=client_handler.start, daemon=True)
    client_thread.start()

    # Start market data generator (simulate price ticks).
    md_thread = threading.Thread(target=market_data.run, kwargs={"duration": simulation_duration}, daemon=True)
    md_thread.start()

    # Start bot traders in separate threads.
    bot_threads = []
    for bot in bots:
        t = threading.Thread(target=bot.run, kwargs={"duration": simulation_duration}, daemon=True)
        t.start()
        bot_threads.append(t)

    # Wait for bot and market data threads to complete.
    for t in bot_threads:
        t.join()
    md_thread.join()

    logger.info("Simulation complete. Shutting down.")
