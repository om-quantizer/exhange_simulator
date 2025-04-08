# config.py
import time
import random

# Use a dynamic seed each run to avoid the same sequence
random.seed(int(time.time() * 1e6))

# Symbol and initial price
SYMBOL = "SBIN"
INITIAL_PRICE = 700.0

# Time step for each bot's personal price update
TICK_INTERVAL = 1  # 1ms (example)

# PRE_MARKET_DURATION = 2  # Duration in seconds for pre-market population phase

# Multi-day simulation settings
SEC_PER_DAY = 1           # 60 seconds = 1 "day" in the simulation
NUM_DAYS = 2               # How many "days" to simulate total*

# Daily band parameters (used directly in MatchingEngine)
MAX_DAILY_MOVE_PERCENT = 10.0       # Starting daily band of ±10% around the open
BAND_EXPANSION_INCREMENT = 5.0      # Expand the band by 5% if the boundary is hit

# config.py (new additions)
TER_PERCENT = 4.0  # Orders must lie within ±5% of the daily open price
CIRCUIT_BREAKER_DURATION = 5  # Duration (in seconds) to halt trading after a circuit trigger


OVERNIGHT_GAP_PERCENT = 5      # Maximum additional gap percentage
MIN_OVERNIGHT_GAP_PERCENT = 0.7  # Minimum gap percentage (absolute) that must be applied

# Order quantity constraints
MIN_ORDER_QTY = 1
MAX_ORDER_QTY = 10  # keep small for demonstration

# Participants
NUM_BOTS = 1
NUM_CLIENTS = 2

# TCP/UDP configuration
TCP_HOST = "127.0.0.1"
TCP_PORT = 5000
UDP_GROUP = "224.1.1.1"
UDP_PORT = 5007

# TBT feed specifics
STREAM_ID = 1
TOKEN = 1001
PRICE_MULTIPLIER = 100

# For position limits
POSITION_LIMIT = 5

# # GBM parameters for bots (drift and volatility ranges)
# GBM_DRIFT_RANGE = (-0.0004, 0.0004)      # ±0.03% per time step
# GBM_VOLATILITY_RANGE = (0.0001, 0.001)    # Smaller short-term volatility

GBM_DRIFT_RANGE = (-0.004, 0.004)      # ±0.03% per time step
GBM_VOLATILITY_RANGE = (0.00006, 0.0001)    # Smaller short-term volatility
 

SLIPPAGE_PERCENT = 0.05             # Default slippage percent (not used directly)
CLIENT_SLIPPAGE_PERCENT = 0.1       # Maximum slippage percent for client orders (e.g., 0.1% of price)
BOT_SLIPPAGE_PERCENT = 0.05         # Maximum slippage percent for bot orders (e.g., 0.05% of price)
VOLUME_PEAK_FACTOR = 0.8            # Extra volume multiplier peak at start and end of day (e.g., 50% increase)


NEWS_SHOCK_PROB = 0.1       # Daily probability of a news shock event occurring during the day
MIN_SHOCK_PERCENT = 10.0     # Minimum percentage change due to a shock event
MAX_SHOCK_PERCENT = 20.0    # Maximum percentage change due to a shock event
