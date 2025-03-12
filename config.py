# config.py
# Configuration and hyperparameters for the exchange simulator.

# Security and price settings.
SYMBOL = "SBIN"
INITIAL_PRICE = 700.0    # Initial price of SBIN in INR.
# TICK_INTERVAL = 0.000001 # Microsecond-level tick interval (in seconds).
TICK_INTERVAL = 0.0001 # Millisecond-level tick interval (in seconds).

# GBM model parameters for price simulation.
GBM_DRIFT = 0.0          # Drift (mu) for GBM.
GBM_VOLATILITY = 0.02    # Volatility (sigma) for GBM.

# Participants.
NUM_BOTS = 10             # Number of bot traders.
NUM_CLIENTS = 2          # Number of client connections to accept.

# Network configuration.
TCP_HOST = "127.0.0.1"
TCP_PORT = 5000          # TCP port for client connections.
UDP_GROUP = "224.1.1.1"  # Multicast group for UDP feed.
UDP_PORT = 5007          # UDP port for multicast feed.

# NSE TBT feed specifics (simplified).
STREAM_ID = 1            # Stream identifier.
TOKEN = 1001             # Unique token/contract ID for SBIN.
PRICE_MULTIPLIER = 100   # Price multiplier (converting INR to paise as integer).
