# network.py
# UDP multicast feed for broadcasting orders, trades, and cancellations.
# Messages follow a simplified binary format inspired by the NSE TBT protocol.

import socket, struct, itertools, time
from utils import enforce_tick
import config

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack('b', 1))

# Sequence number generator for messages.
_seq_gen = itertools.count(1)
def _next_sequence():
    return next(_seq_gen)

def _check_uint32(value, name):
    ivalue = int(value)
    if not (0 <= ivalue <= 0xFFFFFFFF):
        raise ValueError(f"{name} value {ivalue} is out of 32-bit unsigned int range")
    return ivalue

def send_order(order):
    seq = _next_sequence()
    timestamp = int(order.timestamp_ns)   # Expect timestamp in ns (Q field)
    order_id = float(order.id)              # Order id as float (8-byte double)
    token = _check_uint32(config.TOKEN, "TOKEN")
    msg_type = b'N'
    side_byte = b'B' if order.side.upper() == 'B' else b'S'
    
    price = enforce_tick(order.price)
    price_int = _check_uint32(round(price * config.PRICE_MULTIPLIER), "price_int")
    qty = _check_uint32(order.quantity, "quantity")
    
    try:
        packet = struct.pack('<HIcQdIcII',
                             config.STREAM_ID, _check_uint32(seq, "sequence"), msg_type,
                             timestamp, order_id, token, side_byte,
                             price_int, qty)
    except struct.error as se:
        raise struct.error(f"Error packing order: {se}. Values: STREAM_ID={config.STREAM_ID}, seq={seq}, "
                           f"msg_type={msg_type}, timestamp={timestamp}, order_id={order_id}, "
                           f"token={token}, side_byte={side_byte}, price_int={price_int}, qty={qty}")
    sock.sendto(packet, (config.UDP_GROUP, config.UDP_PORT))

def send_trade(buy_id, sell_id, trade_price, trade_qty):
    seq = _next_sequence()
    timestamp = time.time_ns()
    buy_id_f = float(buy_id)
    sell_id_f = float(sell_id)
    token = _check_uint32(config.TOKEN, "TOKEN")
    msg_type = b'T'
    price = enforce_tick(trade_price)
    price_int = _check_uint32(round(price * config.PRICE_MULTIPLIER), "price_int")
    qty = _check_uint32(trade_qty, "trade_qty")
    
    packet = struct.pack('<HIcQddIII',
                         config.STREAM_ID, _check_uint32(seq, "sequence"), msg_type,
                         timestamp, buy_id_f, sell_id_f,
                         token, price_int, qty)
    sock.sendto(packet, (config.UDP_GROUP, config.UDP_PORT))

def send_cancel(order):
    seq = _next_sequence()
    timestamp = time.time_ns()
    order_id = float(order.id)
    token = _check_uint32(config.TOKEN, "TOKEN")
    msg_type = b'X'
    side_byte = b'B' if order.side.upper() == 'B' else b'S'
    price = enforce_tick(order.price)
    price_int = _check_uint32(round(price * config.PRICE_MULTIPLIER), "price_int")
    qty = _check_uint32(order.quantity, "quantity")
    
    packet = struct.pack('<HIcQdIcII',
                         config.STREAM_ID, _check_uint32(seq, "sequence"), msg_type,
                         timestamp, order_id, token, side_byte,
                         price_int, qty)
    sock.sendto(packet, (config.UDP_GROUP, config.UDP_PORT))

def send_cancel_ack(order):
    seq = _next_sequence()
    timestamp = time.time_ns()
    order_id = float(order.id)
    token = _check_uint32(config.TOKEN, "TOKEN")
    msg_type = b'K'  # 'K' indicates a cancel acknowledgment.
    side_byte = b'B' if order.side.upper() == 'B' else b'S'
    price = enforce_tick(order.price)
    price_int = _check_uint32(round(price * config.PRICE_MULTIPLIER), "price_int")
    qty = _check_uint32(order.quantity, "quantity")
    
    packet = struct.pack('<HIcQdIcII',
                         config.STREAM_ID, _check_uint32(seq, "sequence"), msg_type,
                         timestamp, order_id, token, side_byte,
                         price_int, qty)
    sock.sendto(packet, (config.UDP_GROUP, config.UDP_PORT))

def send_edit_ack(order):
    seq = _next_sequence()
    timestamp = time.time_ns()
    order_id = float(order.id)
    token = _check_uint32(config.TOKEN, "TOKEN")
    msg_type = b'E'  # 'E' indicates an edit acknowledgment.
    side_byte = b'B' if order.side.upper() == 'B' else b'S'
    price = enforce_tick(order.price)
    price_int = _check_uint32(round(price * config.PRICE_MULTIPLIER), "price_int")
    qty = _check_uint32(order.quantity, "quantity")
    
    packet = struct.pack('<HIcQdIcII',
                         config.STREAM_ID, _check_uint32(seq, "sequence"), msg_type,
                         timestamp, order_id, token, side_byte,
                         price_int, qty)
    sock.sendto(packet, (config.UDP_GROUP, config.UDP_PORT))

def send_rejection(order):
    seq = _next_sequence()
    timestamp = time.time_ns()
    order_id = float(order.id)
    token = _check_uint32(config.TOKEN, "TOKEN")
    msg_type = b'R'  # 'R' indicates a rejection message.
    side_byte = b'B' if order.side.upper() == 'B' else b'S'
    price = enforce_tick(order.price)
    price_int = _check_uint32(round(price * config.PRICE_MULTIPLIER), "price_int")
    qty = _check_uint32(order.quantity, "quantity")
    
    packet = struct.pack('<HIcQdIcII',
                         config.STREAM_ID, _check_uint32(seq, "sequence"), msg_type,
                         timestamp, order_id, token, side_byte,
                         price_int, qty)
    sock.sendto(packet, (config.UDP_GROUP, config.UDP_PORT))
