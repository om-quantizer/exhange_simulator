# network.py
# UDP multicast feed for broadcasting orders, trades, and cancellations.
# Messages follow a simplified binary format inspired by the NSE TBT protocol.

import socket, struct, itertools, time
from utils import enforce_tick
import config

# Set up UDP socket for multicast.
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack('b', 1))

# Sequence number generator for messages.
_seq_gen = itertools.count(1)
def _next_sequence():
    return next(_seq_gen)

def send_order(order):
    """
    Send a New Order message (type 'N') with the following binary structure:
    Header: STREAM_ID (2 bytes), Sequence (4 bytes)
    Payload: MsgType (1 byte), Timestamp (8 bytes), OrderID (8 bytes as float),
             Token (4 bytes), OrderSide (1 byte), Price (4 bytes, int paise), Quantity (4 bytes)
    """
    seq = _next_sequence()
    timestamp = order.timestamp_ns
    order_id = float(order.id)
    token = config.TOKEN
    msg_type = b'N'
    side_byte = b'B' if order.side == 'B' else b'S'
    price = enforce_tick(order.price)
    price_int = int(price * config.PRICE_MULTIPLIER)
    qty = order.quantity
    packet = struct.pack('<HIcQdIcII',
                         config.STREAM_ID, seq, msg_type,
                         timestamp, order_id, token, side_byte,
                         price_int, qty)
    sock.sendto(packet, (config.UDP_GROUP, config.UDP_PORT))

def send_trade(buy_id, sell_id, trade_price, trade_qty):
    """
    Send a Trade message (type 'T') with the following binary structure:
    Header: STREAM_ID (2 bytes), Sequence (4 bytes)
    Payload: MsgType (1 byte), Timestamp (8 bytes), BuyOrderID (8 bytes as float),
             SellOrderID (8 bytes as float), Token (4 bytes), TradePrice (4 bytes, int paise), TradeQty (4 bytes)
    """
    seq = _next_sequence()
    timestamp = time.time_ns()
    buy_id_f = float(buy_id)
    sell_id_f = float(sell_id)
    token = config.TOKEN
    msg_type = b'T'
    price = enforce_tick(trade_price)
    price_int = int(price * config.PRICE_MULTIPLIER)
    packet = struct.pack('<HIcQddIII',
                         config.STREAM_ID, seq, msg_type,
                         timestamp, buy_id_f, sell_id_f,
                         token, price_int, trade_qty)
    sock.sendto(packet, (config.UDP_GROUP, config.UDP_PORT))

def send_cancel(order):
    """
    Send an Order Cancellation message (type 'X') with the same structure as New Order.
    """
    seq = _next_sequence()
    timestamp = time.time_ns()
    order_id = float(order.id)
    token = config.TOKEN
    msg_type = b'X'
    side_byte = b'B' if order.side == 'B' else b'S'
    price = enforce_tick(order.price)
    price_int = int(price * config.PRICE_MULTIPLIER)
    qty = order.quantity
    packet = struct.pack('<HIcQdIcII',
                         config.STREAM_ID, seq, msg_type,
                         timestamp, order_id, token, side_byte,
                         price_int, qty)
    sock.sendto(packet, (config.UDP_GROUP, config.UDP_PORT))

def send_cancel_ack(order):
    """
    Send a Cancellation Acknowledgement message (type 'K') for a cancelled order.
    """
    seq = _next_sequence()
    timestamp = time.time_ns()
    order_id = float(order.id)
    token = config.TOKEN
    msg_type = b'K'
    side_byte = b'B' if order.side == 'B' else b'S'
    price = enforce_tick(order.price)
    price_int = int(price * config.PRICE_MULTIPLIER)
    qty = order.quantity
    packet = struct.pack('<HIcQdIcII',
                         config.STREAM_ID, seq, msg_type,
                         timestamp, order_id, token, side_byte,
                         price_int, qty)
    sock.sendto(packet, (config.UDP_GROUP, config.UDP_PORT))

def send_edit_ack(order):
    """
    Send an Edit Acknowledgement message (type 'E') for an edited order.
    """
    seq = _next_sequence()
    timestamp = time.time_ns()
    order_id = float(order.id)
    token = config.TOKEN
    msg_type = b'E'
    side_byte = b'B' if order.side == 'B' else b'S'
    price = enforce_tick(order.price)
    price_int = int(price * config.PRICE_MULTIPLIER)
    qty = order.quantity
    packet = struct.pack('<HIcQdIcII',
                         config.STREAM_ID, seq, msg_type,
                         timestamp, order_id, token, side_byte,
                         price_int, qty)
    sock.sendto(packet, (config.UDP_GROUP, config.UDP_PORT))
