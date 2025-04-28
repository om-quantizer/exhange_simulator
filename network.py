# network.py
# UDP multicast layer: broadcasts all new orders, trades, cancellations, and acknowledgments
# in a simplified binary format inspired by the NSE’s TBT feed.

import socket                    # Low-level networking interface
import struct                    # Packing/unpacking binary data
import itertools                 # For sequence number generation
import time                      # Timestamps for trade messages
from utils import enforce_tick   # Ensure price aligns to tick size
import config                    # Contains UDP group, port, protocol constants

# Create UDP socket for multicast (IPv4, UDP)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
# Set TTL = 1 so packets stay within local network
sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack('b', 1))

# Global counter for message sequence numbers (monotonic)
_seq_gen = itertools.count(1)

def _next_sequence():
    """Return next 32-bit sequence number for outgoing feed messages."""
    return next(_seq_gen)

def _check_uint32(value, name):
    """
    Validate and convert a value to a 32-bit unsigned int.
    Raises ValueError if outside [0, 2^32-1].
    Used for fields like price_int, quantity, token.
    """
    ivalue = int(value)
    if not (0 <= ivalue <= 0xFFFFFFFF):
        raise ValueError(f"{name} value {ivalue} is out of 32-bit unsigned int range")
    return ivalue

def send_order(order):
    """
    Broadcast a New Order ('N') message with fields:
      - STREAM_ID: feed identifier
      - sequence: monotonic counter
      - timestamp: nanoseconds since epoch
      - order_id: 8-byte double
      - token: exchange token (uint32)
      - side: 'B' or 'S'
      - price_int: price * PRICE_MULTIPLIER as uint32
      - qty: order quantity
    """
    seq = _next_sequence()
    timestamp = int(order.timestamp_ns)
    order_id = float(order.id)
    token = _check_uint32(config.TOKEN, "TOKEN")
    msg_type = b'N'
    side_byte = b'B' if order.side.upper() == 'B' else b'S'
    # Convert price to integer ticks
    price = enforce_tick(order.price)
    price_int = _check_uint32(round(price * config.PRICE_MULTIPLIER), "price_int")
    qty = _check_uint32(order.quantity, "quantity")

    # Pack fields in little-endian (<), types: H=uint16, I=uint32, c=char, Q=uint64, d=double
    packet = struct.pack(
        '<HIcQdIcII',
        config.STREAM_ID,
        _check_uint32(seq, "sequence"),
        msg_type,
        timestamp,
        order_id,
        token,
        side_byte,
        price_int,
        qty
    )
    # Send to multicast group and port
    sock.sendto(packet, (config.UDP_GROUP, config.UDP_PORT))

def send_trade(buy_id, sell_id, trade_price, trade_qty):
    """
    Broadcast a Trade ('T') message with:
      - buy_id, sell_id as doubles
      - same fields as order: sequence, timestamp, token, price_int, qty
    """
    seq = _next_sequence()
    timestamp = time.time_ns()        # use wall-clock for trades
    buy_id_f = float(buy_id)
    sell_id_f = float(sell_id)
    token = _check_uint32(config.TOKEN, "TOKEN")
    msg_type = b'T'
    price = enforce_tick(trade_price)
    price_int = _check_uint32(round(price * config.PRICE_MULTIPLIER), "price_int")
    qty = _check_uint32(trade_qty, "trade_qty")

    packet = struct.pack(
        '<HIcQddIII',
        config.STREAM_ID,
        _check_uint32(seq, "sequence"),
        msg_type,
        timestamp,
        buy_id_f,
        sell_id_f,
        token,
        price_int,
        qty
    )
    sock.sendto(packet, (config.UDP_GROUP, config.UDP_PORT))

def send_cancel(order):
    """
    Broadcast a Cancel ('X') message mirroring send_order format:
      - Indicates order_id is being cancelled (order.active -> False)
    """
    seq = _next_sequence()
    timestamp = time.time_ns()
    order_id = float(order.id)
    token = _check_uint32(config.TOKEN, "TOKEN")
    msg_type = b'X'
    side_byte = b'B' if order.side.upper() == 'B' else b'S'
    price = enforce_tick(order.price)
    price_int = _check_uint32(round(price * config.PRICE_MULTIPLIER), "price_int")
    qty = _check_uint32(order.quantity, "quantity")

    packet = struct.pack(
        '<HIcQdIcII',
        config.STREAM_ID,
        _check_uint32(seq, "sequence"),
        msg_type,
        timestamp,
        order_id,
        token,
        side_byte,
        price_int,
        qty
    )
    sock.sendto(packet, (config.UDP_GROUP, config.UDP_PORT))

def send_cancel_ack(order):
    """
    Broadcast a Cancel Acknowledgment ('K'):
      - Same fields as cancel, but msg_type 'K'
      - Clients use this to confirm cancellation was processed.
    """
    seq = _next_sequence()
    timestamp = time.time_ns()
    order_id = float(order.id)
    token = _check_uint32(config.TOKEN, "TOKEN")
    msg_type = b'K'
    side_byte = b'B' if order.side.upper() == 'B' else b'S'
    price = enforce_tick(order.price)
    price_int = _check_uint32(round(price * config.PRICE_MULTIPLIER), "price_int")
    qty = _check_uint32(order.quantity, "quantity")

    packet = struct.pack(
        '<HIcQdIcII',
        config.STREAM_ID,
        _check_uint32(seq, "sequence"),
        msg_type,
        timestamp,
        order_id,
        token,
        side_byte,
        price_int,
        qty
    )
    sock.sendto(packet, (config.UDP_GROUP, config.UDP_PORT))

def send_edit_ack(order):
    """
    Broadcast an Edit Acknowledgment ('E'):
      - Clients use this to confirm their edit request succeeded.
      - Fields mirror cancel_ack.
    """
    seq = _next_sequence()
    timestamp = time.time_ns()
    order_id = float(order.id)
    token = _check_uint32(config.TOKEN, "TOKEN")
    msg_type = b'E'
    side_byte = b'B' if order.side.upper() == 'B' else b'S'
    price = enforce_tick(order.price)
    price_int = _check_uint32(round(price * config.PRICE_MULTIPLIER), "price_int")
    qty = _check_uint32(order.quantity, "quantity")

    packet = struct.pack(
        '<HIcQdIcII',
        config.STREAM_ID,
        _check_uint32(seq, "sequence"),
        msg_type,
        timestamp,
        order_id,
        token,
        side_byte,
        price_int,
        qty
    )
    sock.sendto(packet, (config.UDP_GROUP, config.UDP_PORT))

def send_rejection(order):
    """
    Broadcast a Rejection ('R'):
      - Indicates an incoming order was refused (e.g., price outside TER or circuit open).
    """
    seq = _next_sequence()
    timestamp = time.time_ns()
    order_id = float(order.id)
    token = _check_uint32(config.TOKEN, "TOKEN")
    msg_type = b'R'
    side_byte = b'B' if order.side.upper() == 'B' else b'S'
    price = enforce_tick(order.price)
    price_int = _check_uint32(round(price * config.PRICE_MULTIPLIER), "price_int")
    qty = _check_uint32(order.quantity, "quantity")

    packet = struct.pack(
        '<HIcQdIcII',
        config.STREAM_ID,
        _check_uint32(seq, "sequence"),
        msg_type,
        timestamp,
        order_id,
        token,
        side_byte,
        price_int,
        qty
    )
    sock.sendto(packet, (config.UDP_GROUP, config.UDP_PORT))
