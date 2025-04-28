# trader_profile.py
# Defines trader profiles with additional parameters that influence order generation.
#
# Each profile now has the following parameters:
#   - volume_multiplier: Scales the base order volume.
#   - base_price_offset: A constant offset added to the bot's personal price.
#   - aggression: Pushes the order price away from the personal price.
#   - reaction_speed: Lower values mean the trader reacts (acts) more quickly.
#   - cancellation_rate: Likelihood (0 to 1) that the trader cancels an order.
#   - order_frequency: Multiplier to adjust how frequently new orders are placed.
#   - price_sensitivity: How strongly the trader’s order price changes with market moves.
#   - tick_interval: How frequently the trader updates its personal price (in seconds).

# Expected Trends:
#   • Aggressive Buyer: Places high-volume orders quickly at prices above its personal price.
#     Tends to push the market up with fast, high bids.

#   • Aggressive Seller: Places high-volume orders quickly at prices below its personal price,
#     likely to drive the market down.

#   • Passive: Trades conservatively with moderate volume and reaction; orders stay near the
#     personal price, exerting little directional pressure.

#   • Market Maker: Places orders on both sides with moderate volume and high cancellation
#     rate; aims to capture bid-ask spreads rather than directional moves.

#   • Contrarian Buyer: Looks for dips (with a slight negative base offset) and reacts moderately;
#     may buy when others are selling, but with lower aggression.

#   • Contrarian Seller: Similarly, may sell when prices rise, with moderate behavior.

#   • Momentum Trader: Reacts very quickly and aggressively, placing orders that follow market
#     trends, which can amplify trends.

#   • Risk Averse: Places smaller, less frequent orders and reacts slowly; tends to stabilize the market.

#   • High Frequency: Acts extremely fast with low volume and minimal price shifts; their orders are short-lived and continuously updated.


# trade_profile.py
from utils import enforce_tick
import random
import config

class TraderProfile:
    def __init__(self, name, volume_multiplier=1.0, base_price_offset=0.0, aggression=0.0,
                 reaction_speed=0.5, cancellation_rate=0.1, order_frequency=1.0,
                 price_sensitivity=1.0, tick_interval=0.2,
                 mu_range=None, sigma_range=None):
        self.name = name
        self.volume_multiplier = volume_multiplier  # scales order size
        self.base_price_offset = base_price_offset      # shifts the personal price
        self.aggression = aggression                    # how far orders deviate from personal price
        self.reaction_speed = reaction_speed            # how fast the trader reacts
        self.cancellation_rate = cancellation_rate      # likelihood to cancel orders
        self.order_frequency = order_frequency          # frequency of order submissions
        self.price_sensitivity = price_sensitivity      # sensitivity to market moves
        self.tick_interval = tick_interval              # update interval for personal price
        self.mu_range = mu_range
        self.sigma_range = sigma_range

    def aggression_for_side(self, side):
        # Buyers have positive aggression; sellers negative.
        return abs(self.aggression) if side.upper() == "B" else -abs(self.aggression)
        
    def compute_order_price(self, bot, side, best_bid_price, best_ask_price):
        # For Trend Reversal Trader:
        if self.name == "Trend Reversal Trader":
            trend = bot.engine.get_market_trend()
            if trend == "bullish":
                base_price = bot.personal_price - 0.05 if side == 'B' else bot.personal_price + 0.05
            elif trend == "bearish":
                base_price = bot.personal_price + 0.05 if side == 'B' else bot.personal_price - 0.05
            else:
                base_price = bot.personal_price
            random_offset = random.uniform(-0.05, 0.05)
            return enforce_tick(base_price + random_offset)
        # For Market Maker:
        elif self.name == "Market Maker":
            if side == 'B' and best_bid_price is not None:
                base_price = best_bid_price + 0.05
            elif side == 'S' and best_ask_price is not None:
                base_price = best_ask_price - 0.05
            else:
                base_price = bot.personal_price
            random_offset = random.uniform(-0.15, 0.15)
            return enforce_tick(base_price + random_offset)
        # For Momentum Trader: use best quote for immediate execution.
        elif self.name == "Momentum Trader":
            if side == 'B' and best_ask_price is not None:
                return best_ask_price
            elif side == 'S' and best_bid_price is not None:
                return best_bid_price
            else:
                random_offset = random.uniform(-0.05, 0.05)
                return enforce_tick(bot.personal_price + self.aggression_for_side(side) + random_offset)
        else:



            random_offset = random.uniform(-0.05, 0.05)
            return enforce_tick(bot.personal_price + self.base_price_offset + self.aggression_for_side(side) + random_offset)

    def __repr__(self):
        return (f"<TraderProfile {self.name}: vol_mul={self.volume_multiplier}, offset={self.base_price_offset}, "
                f"agg={self.aggression}, react={self.reaction_speed}, cancel_rate={self.cancellation_rate}, "
                f"order_freq={self.order_frequency}, price_sens={self.price_sensitivity}, tick_int={self.tick_interval}, "
                f"mu_range={self.mu_range}, sigma_range={self.sigma_range}>")

# Derive base values from config:

base_drift_min, base_drift_max = config.GBM_DRIFT_RANGE   # e.g., (-0.05, 0.05)
base_vol = config.GBM_VOLATILITY_RANGE[0]                # e.g., 0.005

# Now define profiles relative to the config settings:
AGGRESSIVE_BUYER = TraderProfile(
    "Aggressive Buyer",
    volume_multiplier=1.2,
    base_price_offset=0.05,
    aggression=0.20,
    reaction_speed=0.10,
    cancellation_rate=0.03,
    order_frequency=1.8,
    price_sensitivity=1.4,
    tick_interval=0.1,
    mu_range=(0.4 * base_drift_max, 1.0 * base_drift_max),      # (0.02, 0.05) if base_drift_max=0.05
    sigma_range=(1.4 * base_vol, 2.0 * base_vol)                # (0.007, 0.01) if base_vol=0.005
)

AGGRESSIVE_SELLER = TraderProfile(
    "Aggressive Seller",
    volume_multiplier=1.2,
    base_price_offset=-0.05,
    aggression=0.20,
    reaction_speed=0.10,
    cancellation_rate=0.03,
    order_frequency=1.8,
    price_sensitivity=1.4,
    tick_interval=0.1,
    mu_range=(1.0 * base_drift_min, 0.4 * base_drift_min),      # (-0.05, -0.02)
    sigma_range=(1.4 * base_vol, 2.0 * base_vol)
)

PASSIVE = TraderProfile(
    "Passive",
    volume_multiplier=1.0,
    base_price_offset=0.0,
    aggression=0.0,
    reaction_speed=1.0,
    cancellation_rate=0.1,
    order_frequency=1.0,
    price_sensitivity=0.7,
    tick_interval=1.00,
    mu_range=(-0.1 * base_drift_max, 0.1 * base_drift_max),     # (-0.005, 0.005)
    sigma_range=(0.6 * base_vol, 1.0 * base_vol)                 # (0.003, 0.005)
)

MARKET_MAKER = TraderProfile(
    "Market Maker",
    volume_multiplier=2.3,
    base_price_offset=0.0,
    aggression=0.05,
    reaction_speed=0.20,
    cancellation_rate=0.3,
    order_frequency=1.4,
    price_sensitivity=1.0,
    tick_interval=0.50,
    mu_range=(-0.1 * base_drift_max, 0.1 * base_drift_max),     # similar to Passive
    sigma_range=(0.6 * base_vol, 1.0 * base_vol)
)

CONTRARIAN_BUYER = TraderProfile(
    "Contrarian Buyer",
    volume_multiplier=1.1,
    base_price_offset=-0.10,
    aggression=0.10,
    reaction_speed=0.60,
    cancellation_rate=0.10,
    order_frequency=0.8,
    price_sensitivity=0.8,
    tick_interval=0.40,
    mu_range=(-0.1 * base_drift_max, 0.1 * base_drift_max),     # (-0.005, 0.005)
    sigma_range=(0.6 * base_vol, 1.0 * base_vol)
)

CONTRARIAN_SELLER = TraderProfile(
    "Contrarian Seller",
    volume_multiplier=1.1,
    base_price_offset=0.10,
    aggression=0.10,
    reaction_speed=0.60,
    cancellation_rate=0.10,
    order_frequency=0.8,
    price_sensitivity=0.8,
    tick_interval=0.40,
    mu_range=(-0.1 * base_drift_max, 0.1 * base_drift_max),
    sigma_range=(0.6 * base_vol, 1.0 * base_vol)
)

MOMENTUM_TRADER = TraderProfile(
    "Momentum Trader",
    volume_multiplier=2.0,
    base_price_offset=0.05,
    aggression=0.05,
    reaction_speed=0.10,
    cancellation_rate=0.08,
    order_frequency=2.5,
    price_sensitivity=1.8,
    tick_interval=0.05,
    mu_range=(0.1 * base_drift_max, 0.4 * base_drift_max),      # (0.005, 0.02)
    sigma_range=(1.4 * base_vol, 2.4 * base_vol)                 # (0.007, 0.012)
)

RISK_AVERSE = TraderProfile(
    "Risk Averse",
    volume_multiplier=0.6,
    base_price_offset=0.0,
    aggression=0.0,
    reaction_speed=1.5,
    cancellation_rate=0.5,
    order_frequency=0.6,
    price_sensitivity=0.5,
    tick_interval=1.0,
    mu_range=(-0.04 * base_drift_max, 0.04 * base_drift_max),    # (-0.002, 0.002)
    sigma_range=(0.4 * base_vol, 0.8 * base_vol)                 # (0.002, 0.004)
)

HIGH_FREQUENCY = TraderProfile(
    "High Frequency",
    volume_multiplier=0.4,
    base_price_offset=0.0,
    aggression=0.01,
    reaction_speed=0.03,
    cancellation_rate=0.15,
    order_frequency=4.0,
    price_sensitivity=0.95,
    tick_interval=0.01,
    mu_range=(-0.06 * base_drift_max, 0.06 * base_drift_max),    # (-0.003, 0.003)
    sigma_range=(0.4 * base_vol, 0.8 * base_vol)                 # (0.002, 0.004)
)

TREND_REVERSAL_TRADER = TraderProfile(
    "Trend Reversal Trader",
    volume_multiplier=1.1,
    base_price_offset=0.0,
    aggression=0.03,
    reaction_speed=0.3,
    cancellation_rate=0.2,
    order_frequency=1.2,
    price_sensitivity=1.0,
    tick_interval=0.3,
    mu_range=(-0.1 * base_drift_max, 0.1 * base_drift_max),     # (-0.005, 0.005)
    sigma_range=(0.6 * base_vol, 1.0 * base_vol)
)

# from utils import enforce_tick
# import random
# import config

# class TraderProfile:
#     def __init__(self, name, volume_multiplier=1.0, base_price_offset=0.0, aggression=0.0,
#                  reaction_speed=0.5, cancellation_rate=0.1, order_frequency=1.0,
#                  price_sensitivity=1.0, tick_interval=0.2,
#                  mu_range=None, sigma_range=None, cash_range=None, share_range=None,
#                  trading_duration_fraction=None):
#         self.name = name
#         self.volume_multiplier = volume_multiplier  # scales order size
#         self.base_price_offset = base_price_offset      # shifts the personal price
#         self.aggression = aggression                    # price deviation factor
#         self.reaction_speed = reaction_speed            # reaction time (lower means slower)
#         self.cancellation_rate = cancellation_rate      # likelihood to cancel orders
#         self.order_frequency = order_frequency          # frequency of order submissions
#         self.price_sensitivity = price_sensitivity      # sensitivity to market moves
#         self.tick_interval = tick_interval              # update interval for personal price
#         self.mu_range = mu_range
#         self.sigma_range = sigma_range
#         self.cash_range = cash_range if cash_range is not None else (config.INITIAL_CAPITAL * 0.9, config.INITIAL_CAPITAL * 1.1)
#         self.share_range = share_range if share_range is not None else (config.INITIAL_SHARES, config.INITIAL_SHARES)
#         # Trading duration fraction: fraction of SEC_PER_DAY this profile remains active.
#         self.trading_duration_fraction = trading_duration_fraction if trading_duration_fraction is not None else 0.6

#     def aggression_for_side(self, side):
#         # Buyers have positive aggression, sellers negative.
#         return abs(self.aggression) if side.upper() == "B" else -abs(self.aggression)
        
#     def compute_order_price(self, bot, side, best_bid_price, best_ask_price):
#         # Special case for Trend Reversal Trader.
#         if self.name == "Trend Reversal Trader":
#             trend = bot.engine.get_market_trend()
#             if trend == "bullish":
#                 base_price = bot.personal_price - 0.05 if side == 'B' else bot.personal_price + 0.05
#             elif trend == "bearish":
#                 base_price = bot.personal_price + 0.05 if side == 'B' else bot.personal_price - 0.05
#             else:
#                 base_price = bot.personal_price
#             random_offset = random.uniform(-0.05, 0.05)
#             return enforce_tick(base_price + random_offset)
#         # For Market Maker.
#         elif self.name == "Market Maker":
#             if side == 'B' and best_bid_price is not None:
#                 base_price = best_bid_price + 0.05
#             elif side == 'S' and best_ask_price is not None:
#                 base_price = best_ask_price - 0.05
#             else:
#                 base_price = bot.personal_price
#             random_offset = random.uniform(-0.15, 0.15)
#             return enforce_tick(base_price + random_offset)
#         # For Momentum Trader.
#         elif self.name == "Momentum Trader":
#             if side == 'B' and best_ask_price is not None:
#                 return best_ask_price
#             elif side == 'S' and best_bid_price is not None:
#                 return best_bid_price
#             else:
#                 random_offset = random.uniform(-0.05, 0.05)
#                 return enforce_tick(bot.personal_price + self.aggression_for_side(side) + random_offset)
#         else:
#             random_offset = random.uniform(-0.05, 0.05)
#             return enforce_tick(bot.personal_price + self.base_price_offset + self.aggression_for_side(side) + random_offset)

#     def __repr__(self):
#         return (f"<TraderProfile {self.name}: vol_mul={self.volume_multiplier}, offset={self.base_price_offset}, "
#                 f"agg={self.aggression}, react={self.reaction_speed}, cancel_rate={self.cancellation_rate}, "
#                 f"order_freq={self.order_frequency}, price_sens={self.price_sensitivity}, tick_int={self.tick_interval}, "
#                 f"mu_range={self.mu_range}, sigma_range={self.sigma_range}, "
#                 f"cash_range={self.cash_range}, share_range={self.share_range}, "
#                 f"duration_fraction={self.trading_duration_fraction}>")

# # Base parameters derived from config.
# base_drift_min, base_drift_max = config.GBM_DRIFT_RANGE  
# base_vol = config.GBM_VOLATILITY_RANGE[0]

# AGGRESSIVE_BUYER = TraderProfile(
#     "Aggressive Buyer",
#     volume_multiplier=1.2,
#     base_price_offset=0.05,
#     aggression=0.20,
#     reaction_speed=0.10,
#     cancellation_rate=0.03,
#     order_frequency=1.8,
#     price_sensitivity=1.4,
#     tick_interval=0.1,
#     mu_range=(0.4 * base_drift_max, 1.0 * base_drift_max),
#     sigma_range=(1.4 * base_vol, 2.0 * base_vol),
#     cash_range=(config.INITIAL_CAPITAL * 0.95, config.INITIAL_CAPITAL * 1.05),
#     share_range=(800, 1200),
#     trading_duration_fraction=0.6  # Designed as short-term aggressive.
# )

# AGGRESSIVE_SELLER = TraderProfile(
#     "Aggressive Seller",
#     volume_multiplier=1.2,
#     base_price_offset=-0.05,
#     aggression=0.20,
#     reaction_speed=0.10,
#     cancellation_rate=0.03,
#     order_frequency=1.8,
#     price_sensitivity=1.4,
#     tick_interval=0.1,
#     mu_range=(1.0 * base_drift_min, 0.4 * base_drift_min),
#     sigma_range=(1.4 * base_vol, 2.0 * base_vol),
#     cash_range=(config.INITIAL_CAPITAL * 0.95, config.INITIAL_CAPITAL * 1.05),
#     share_range=(800, 1200),
#     trading_duration_fraction=0.6
# )

# PASSIVE = TraderProfile(
#     "Passive",
#     volume_multiplier=1.0,
#     base_price_offset=0.0,
#     aggression=0.0,
#     reaction_speed=1.0,
#     cancellation_rate=0.1,
#     order_frequency=1.0,
#     price_sensitivity=0.7,
#     tick_interval=1.00,
#     mu_range=(-0.1 * base_drift_max, 0.1 * base_drift_max),
#     sigma_range=(0.6 * base_vol, 1.0 * base_vol),
#     cash_range=(config.INITIAL_CAPITAL * 1.0, config.INITIAL_CAPITAL * 1.0),
#     share_range=(1000, 1500),
#     trading_duration_fraction=0.9  # Passive investors hold longer.
# )

# MARKET_MAKER = TraderProfile(
#     "Market Maker",
#     volume_multiplier=2.3,
#     base_price_offset=0.0,
#     aggression=0.05,
#     reaction_speed=0.20,
#     cancellation_rate=0.3,
#     order_frequency=1.4,
#     price_sensitivity=1.0,
#     tick_interval=0.50,
#     mu_range=(-0.1 * base_drift_max, 0.1 * base_drift_max),
#     sigma_range=(0.6 * base_vol, 1.0 * base_vol),
#     cash_range=(config.INITIAL_CAPITAL * 1.1, config.INITIAL_CAPITAL * 1.2),
#     share_range=(1200, 1800),
#     trading_duration_fraction=0.7  # Typically medium-term participation.
# )

# CONTRARIAN_BUYER = TraderProfile(
#     "Contrarian Buyer",
#     volume_multiplier=1.1,
#     base_price_offset=-0.10,
#     aggression=0.10,
#     reaction_speed=0.60,
#     cancellation_rate=0.10,
#     order_frequency=0.8,
#     price_sensitivity=0.8,
#     tick_interval=0.40,
#     mu_range=(-0.1 * base_drift_max, 0.1 * base_drift_max),
#     sigma_range=(0.6 * base_vol, 1.0 * base_vol),
#     cash_range=(config.INITIAL_CAPITAL * 1.0, config.INITIAL_CAPITAL * 1.0),
#     share_range=(1000, 1500),
#     trading_duration_fraction=0.9
# )

# CONTRARIAN_SELLER = TraderProfile(
#     "Contrarian Seller",
#     volume_multiplier=1.1,
#     base_price_offset=0.10,
#     aggression=0.10,
#     reaction_speed=0.60,
#     cancellation_rate=0.10,
#     order_frequency=0.8,
#     price_sensitivity=0.8,
#     tick_interval=0.40,
#     mu_range=(-0.1 * base_drift_max, 0.1 * base_drift_max),
#     sigma_range=(0.6 * base_vol, 1.0 * base_vol),
#     cash_range=(config.INITIAL_CAPITAL * 1.0, config.INITIAL_CAPITAL * 1.0),
#     share_range=(1000, 1500),
#     trading_duration_fraction=0.9
# )

# MOMENTUM_TRADER = TraderProfile(
#     "Momentum Trader",
#     volume_multiplier=2.0,
#     base_price_offset=0.05,
#     aggression=0.05,
#     reaction_speed=0.10,
#     cancellation_rate=0.08,
#     order_frequency=2.5,
#     price_sensitivity=1.8,
#     tick_interval=0.05,
#     mu_range=(0.1 * base_drift_max, 0.4 * base_drift_max),
#     sigma_range=(1.4 * base_vol, 2.4 * base_vol),
#     cash_range=(config.INITIAL_CAPITAL * 0.95, config.INITIAL_CAPITAL * 1.05),
#     share_range=(800, 1200),
#     trading_duration_fraction=0.6
# )

# RISK_AVERSE = TraderProfile(
#     "Risk Averse",
#     volume_multiplier=0.6,
#     base_price_offset=0.0,
#     aggression=0.0,
#     reaction_speed=1.5,
#     cancellation_rate=0.5,
#     order_frequency=0.6,
#     price_sensitivity=0.5,
#     tick_interval=1.0,
#     mu_range=(-0.04 * base_drift_max, 0.04 * base_drift_max),
#     sigma_range=(0.4 * base_vol, 0.8 * base_vol),
#     cash_range=(config.INITIAL_CAPITAL * 0.9, config.INITIAL_CAPITAL * 1.0),
#     share_range=(1200, 1600),
#     trading_duration_fraction=0.9
# )

# HIGH_FREQUENCY = TraderProfile(
#     "High Frequency",
#     volume_multiplier=0.4,
#     base_price_offset=0.0,
#     aggression=0.01,
#     reaction_speed=0.03,
#     cancellation_rate=0.15,
#     order_frequency=4.0,
#     price_sensitivity=0.95,
#     tick_interval=0.01,
#     mu_range=(-0.06 * base_drift_max, 0.06 * base_drift_max),
#     sigma_range=(0.4 * base_vol, 0.8 * base_vol),
#     cash_range=(config.INITIAL_CAPITAL * 0.95, config.INITIAL_CAPITAL * 1.05),
#     share_range=(500, 800),
#     trading_duration_fraction=0.5  # Very short-term.
# )

# TREND_REVERSAL_TRADER = TraderProfile(
#     "Trend Reversal Trader",
#     volume_multiplier=1.1,
#     base_price_offset=0.0,
#     aggression=0.03,
#     reaction_speed=0.3,
#     cancellation_rate=0.2,
#     order_frequency=1.2,
#     price_sensitivity=1.0,
#     tick_interval=0.3,
#     mu_range=(-0.1 * base_drift_max, 0.1 * base_drift_max),
#     sigma_range=(0.6 * base_vol, 1.0 * base_vol),
#     cash_range=(config.INITIAL_CAPITAL * 1.0, config.INITIAL_CAPITAL * 1.1),
#     share_range=(1000, 1500),
#     trading_duration_fraction=0.6
# )

# # NEW: Investor profile (distinct and separate from other profiles)
# INVESTOR = TraderProfile(
#     "Investor",
#     volume_multiplier=0.8,       # Lower volume relative to aggressive profiles.
#     base_price_offset=0.0,       # Neutral price offset.
#     aggression=0.02,             # Minimal aggression.
#     reaction_speed=0.5,          # Slower reaction.
#     cancellation_rate=0.05,      # Low cancellation tendency.
#     order_frequency=0.5,         # Trades infrequently.
#     price_sensitivity=0.7,       # Moderate sensitivity.
#     tick_interval=1.0,           # Updates personal price slowly.
#     mu_range=(-0.05, 0.05),       # Narrower drift range.
#     sigma_range=(0.001, 0.003),    # Lower volatility.
#     cash_range=(config.INITIAL_CAPITAL * 1.0, config.INITIAL_CAPITAL * 1.2),  # Potentially higher capital.
#     share_range=(config.INITIAL_SHARES, config.INITIAL_SHARES * 2),           # Higher share allocation.
#     trading_duration_fraction=1.0  # Investor remains active nearly the entire day.
# )
