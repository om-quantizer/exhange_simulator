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

from utils import enforce_tick
import random

class TraderProfile:
    def __init__(self, name, volume_multiplier=1.0, base_price_offset=0.0, aggression=0.0,
                 reaction_speed=0.5, cancellation_rate=0.1, order_frequency=1.0,
                 price_sensitivity=1.0, tick_interval=0.2):
        self.name = name
        self.volume_multiplier = volume_multiplier  # Larger multiplier results in larger order sizes.
        self.base_price_offset = base_price_offset      # Adjusts personal price; positive for buyers, negative for sellers.
        self.aggression = aggression                    # Determines how far orders deviate from the personal price.
        self.reaction_speed = reaction_speed            # Lower values yield faster reactions.
        self.cancellation_rate = cancellation_rate      # Higher value increases likelihood of canceling orders.
        self.order_frequency = order_frequency          # Higher value means more frequent order submissions.
        self.price_sensitivity = price_sensitivity      # Higher value causes more aggressive price adjustments.
        self.tick_interval = tick_interval              # Lower values update the personal price more frequently.

    def aggression_for_side(self, side):
        """
        Returns the aggression value with the appropriate sign based on the side.
        For buyers ('B'), aggression is positive; for sellers ('S'), aggression is negative.
        """
        if side.upper() == "B":
            return abs(self.aggression)
        else:
            return -abs(self.aggression)
        
    def compute_order_price(self, bot, side, best_bid_price, best_ask_price):
        # New logic for Trend Reversal Trader:
        if self.name == "Trend Reversal Trader":
            trend = bot.engine.get_market_trend()
            if trend == "bullish":
                # Market is high; expect reversal downward.
                if side == 'B':
                    # For a buy order, try to get a lower entry.
                    base_price = bot.personal_price - 0.05
                else:
                    # For a sell order, try to sell at a premium.
                    base_price = bot.personal_price + 0.05
            elif trend == "bearish":
                # Market is low; expect reversal upward.
                if side == 'B':
                    base_price = bot.personal_price + 0.05
                else:
                    base_price = bot.personal_price - 0.05
            else:
                base_price = bot.personal_price
            random_offset = random.uniform(-0.05, 0.05)
            return enforce_tick(base_price + random_offset)
        elif self.name == "Market Maker":
            if side == 'B' and best_bid_price is not None:
                base_price = best_bid_price + 0.05
            elif side == 'S' and best_ask_price is not None:
                base_price = best_ask_price - 0.05
            else:
                base_price = bot.personal_price
            random_offset = random.uniform(-0.15, 0.15)
            return enforce_tick(base_price + random_offset)
        else:
            random_offset = random.uniform(-0.01, 0.01)
            return enforce_tick(
                bot.personal_price
                + self.base_price_offset
                + self.aggression_for_side(side)
                + random_offset
            )

    def __repr__(self):
        return (f"<TraderProfile {self.name}: vol_mul={self.volume_multiplier}, offset={self.base_price_offset}, "
                f"agg={self.aggression}, react={self.reaction_speed}, cancel_rate={self.cancellation_rate}, "
                f"order_freq={self.order_frequency}, price_sens={self.price_sensitivity}, tick_int={self.tick_interval}>")

# ---------------------------------------------------------------------------
# Significantly distinct profiles based on desired market behaviors:
# ---------------------------------------------------------------------------

# Aggressive Buyer:
# - Very high volume and fast reaction to snap up opportunities.
# - A moderate positive offset ensures bids are placed above the personal price.
# - High aggression pushes orders significantly away from the base.
AGGRESSIVE_BUYER = TraderProfile(
    "Aggressive Buyer",
    volume_multiplier=1.2,    # Large orders to quickly capture assets.
    base_price_offset=0.04,   # Bids above the base price.
    aggression=0.05,          # Strong push away from personal price.
    reaction_speed=0.10,      # Ultra-fast reaction.
    cancellation_rate=0.03,   # Rare cancellations; orders are committed.
    order_frequency=1.8,      # High frequency to continuously enter the market.
    price_sensitivity=1.4,    # Highly reactive to market movements.
    tick_interval=0.08        # Rapid update intervals.
)

# Aggressive Seller:
# - Mirrors the buyer's parameters but with a negative offset to push offers below market.
AGGRESSIVE_SELLER = TraderProfile(
    "Aggressive Seller",
    volume_multiplier=1.2,
    base_price_offset=-0.04,  # Offers below the base price.
    aggression=0.05,
    reaction_speed=0.10,
    cancellation_rate=0.03,
    order_frequency=1.8,
    price_sensitivity=1.4,
    tick_interval=0.08
)

# Passive:
# - Standard order size and frequency with a slow reaction and no aggression.
# - Designed to have minimal influence on market direction.
PASSIVE = TraderProfile(
    "Passive",
    volume_multiplier=1.0,    # Regular volume.
    base_price_offset=0.0,    # No offset; orders at the personal price.
    aggression=0.0,           # No aggressive deviation.
    reaction_speed=1.0,       # Slow reaction, reducing market impact.
    cancellation_rate=0.1,    # Occasional cancellations.
    order_frequency=1.0,      # Standard order frequency.
    price_sensitivity=0.7,    # Low responsiveness.
    tick_interval=0.5         # Infrequent updates.
)

# Market Maker:
# - Provides liquidity by placing orders close to the market price.
# - Uses a high cancellation rate to frequently refresh quotes.
# - Moderate volume with a fast update cycle to adjust for rapid market changes.
MARKET_MAKER = TraderProfile(
    "Market Maker",
    volume_multiplier=2.3,    # Moderately sized orders.
    base_price_offset=0.0,    # Orders placed at market price.
    aggression=0.02,          # Minimal deviation ensures a tight bid/ask spread.
    reaction_speed=0.20,      # Fast enough to adjust quotes.
    cancellation_rate=0.3,    # High cancellation rate to refresh orders.
    order_frequency=1.4,      # Consistent order placements.
    price_sensitivity=1.0,    # Standard responsiveness.
    tick_interval=0.10        # Rapid update cycle.
)

# Contrarian Buyer:
# - Slightly lower volume and a small negative offset to buy on dips.
# - Moderately reactive to avoid overcommitting during reversals.
CONTRARIAN_BUYER = TraderProfile(
    "Contrarian Buyer",
    volume_multiplier=1.1,    # Slightly reduced volume.
    base_price_offset=-0.02,  # Buys at a discount during dips.
    aggression=0.04,          # Mild price adjustment.
    reaction_speed=0.60,      # Moderate reaction speed.
    cancellation_rate=0.10,   # Increased cancellations if the reversal does not materialize.
    order_frequency=0.8,      # Cautious order frequency.
    price_sensitivity=0.8,    # Balanced sensitivity.
    tick_interval=0.40        # Slower updates to prevent overtrading.
)

# Contrarian Seller:
# - Uses the same cautious settings as the buyer but with a positive offset to sell on peaks.
CONTRARIAN_SELLER = TraderProfile(
    "Contrarian Seller",
    volume_multiplier=1.1,
    base_price_offset=0.02,   # Sells at a premium during peaks.
    aggression=0.04,
    reaction_speed=0.60,
    cancellation_rate=0.10,
    order_frequency=0.8,
    price_sensitivity=0.8,
    tick_interval=0.40
)

# Momentum Trader:
# - Combines high volume with an extremely fast reaction to ride the prevailing trend.
# - Strong aggression and sensitivity ensure orders follow momentum closely.
MOMENTUM_TRADER = TraderProfile(
    "Momentum Trader",
    volume_multiplier=2.0,    # Large orders to capitalize on trends.
    base_price_offset=0.05,   # Orders placed further from the base price.
    aggression=0.05,          # Very high aggression to adjust orders swiftly.
    reaction_speed=0.10,      # Ultra-fast reaction to capture trend changes.
    cancellation_rate=0.08,   # Fewer cancellations due to sustained trends.
    order_frequency=2.5,      # Extremely high order frequency.
    price_sensitivity=1.8,    # Orders strongly track market movements.
    tick_interval=0.05        # Ultra-fast updates.
)

# Risk Averse:
# - Trades with very small orders and is slow to react, minimizing exposure.
# - High cancellation rate and low order frequency protect against volatile swings.
RISK_AVERSE = TraderProfile(
    "Risk Averse",
    volume_multiplier=0.6,    # Reduced order size.
    base_price_offset=0.0,    # Neutral pricing.
    aggression=0.0,           # No aggressive moves.
    reaction_speed=1.5,       # Very slow reaction.
    cancellation_rate=0.5,    # High likelihood of cancelling orders in volatile conditions.
    order_frequency=0.6,      # Infrequent order submissions.
    price_sensitivity=0.5,    # Low sensitivity to avoid overtrading.
    tick_interval=1.0         # Slow updates.
)

# High Frequency:
# - Uses minimal volume per order but reacts and updates extremely fast.
# - Very high order frequency allows for rapid, short-lived positions.
HIGH_FREQUENCY = TraderProfile(
    "High Frequency",
    volume_multiplier=0.4,    # Minimal volume per order.
    base_price_offset=0.0,    # Follows market price closely.
    aggression=0.01,          # Barely aggressive to allow minor price adjustments.
    reaction_speed=0.03,      # Ultra-fast reaction speed.
    cancellation_rate=0.15,   # Moderate cancellations to keep orders current.
    order_frequency=4.0,      # Extremely high order frequency.
    price_sensitivity=0.95,   # Moderately reactive to small price changes.
    tick_interval=0.01        # Minimal interval between price updates.
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
    tick_interval=0.3
)