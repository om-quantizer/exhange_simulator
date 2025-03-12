# client_handler.py
# Handles TCP client connections for order submissions, edits, cancellations, and trade confirmations.

import socket
import threading
from utils import enforce_tick
import logging
import config

class ClientHandler:
    def __init__(self, matching_engine):
        self.engine = matching_engine
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind((config.TCP_HOST, config.TCP_PORT))
        self.server.listen(config.NUM_CLIENTS)
        self.log = logging.getLogger("exchange")

    def start(self):
        """Accept client connections and handle them."""
        self.log.info("ClientHandler: Waiting for client connections...")
        client_count = 0
        while client_count < config.NUM_CLIENTS:
            conn, addr = self.server.accept()
            client_count += 1
            self.log.info(f"Client {client_count} connected from {addr}")
            thread = threading.Thread(target=self._handle_client, args=(conn, client_count), daemon=True)
            thread.start()

    def _handle_client(self, conn, client_id):
        """Handle orders and commands from a single client."""
        with conn:
            welcome_msg = (
                f"Welcome Client{client_id}! Connected to the exchange.\n"
                f"Commands:\n"
                f"  - New Order: B <price> <qty> or S <price> <qty>\n"
                f"  - Cancel Order: CANCEL <order_id>\n"
                f"  - Edit Order: EDIT <order_id> <new_price> <new_quantity>\n"
                f"  - EXIT or QUIT to disconnect\n"
            )
            conn.sendall(welcome_msg.encode())
            buffer = ""  # Accumulate data until a newline is encountered.
            try:
                while True:
                    data = conn.recv(1024)
                    if not data:
                        self.log.info(f"Client{client_id} disconnected.")
                        break
                    buffer += data.decode()
                    # Process complete lines only
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        self.log.info(f"Client{client_id} sent: {line}")
                        parts = line.split()
                        cmd = parts[0].upper()
                        try:
                            if cmd in ("EXIT", "QUIT"):
                                conn.sendall(b"Goodbye!\n")
                                self.log.info(f"Client{client_id} requested disconnect.")
                                return
                            elif cmd in ("B", "BUY", "S", "SELL") and len(parts) == 3:
                                side = 'B' if cmd in ("B", "BUY") else 'S'
                                try:
                                    price = enforce_tick(float(parts[1]))
                                    qty = int(parts[2])
                                except ValueError:
                                    conn.sendall(b"ERROR: Invalid price or quantity format.\n")
                                    continue
                                price = enforce_tick(float(parts[1]))
                                self.log.info(f"Processing new order from Client{client_id}: {side} {qty} @ {price}")
                                self.engine.process_order(side, price, qty, owner=conn)
                            elif cmd == "CANCEL" and len(parts) == 2:
                                try:
                                    order_id = int(parts[1])
                                except ValueError:
                                    conn.sendall(b"ERROR: Invalid order ID format.\n")
                                    continue
                                self.log.info(f"Processing CANCEL command for order {order_id} from Client{client_id}")
                                success = self.engine.order_book.cancel_order(order_id)
                                if success:
                                    ack_msg = f"CANCEL ACK: Order {order_id} cancelled successfully.\n"
                                    conn.sendall(ack_msg.encode())
                                    self.log.info(f"Client{client_id} cancelled order {order_id}")
                                else:
                                    conn.sendall(f"ERROR: Order {order_id} could not be cancelled or does not exist.\n".encode())
                            elif cmd == "EDIT" and len(parts) == 4:
                                try:
                                    order_id = int(parts[1])
                                    new_price = enforce_tick(float(parts[2]))
                                    new_quantity = int(parts[3])
                                except ValueError:
                                    conn.sendall(b"ERROR: Invalid format for EDIT command. Use: EDIT <order_id> <new_price> <new_quantity>\n")
                                    continue
                                new_price = enforce_tick(float(parts[2]))
                                self.log.info(f"Processing EDIT command for order {order_id} from Client{client_id} to {new_price} and {new_quantity}")
                                success = self.engine.order_book.edit_order(order_id, new_price=new_price, new_quantity=new_quantity)
                                if success:
                                    ack_msg = f"EDIT ACK: Order {order_id} edited to price {new_price}, quantity {new_quantity}.\n"
                                    conn.sendall(ack_msg.encode())
                                    self.log.info(f"Client{client_id} edited order {order_id} to {new_price} @ {new_quantity}")
                                else:
                                    conn.sendall(f"ERROR: Order {order_id} could not be edited (might be inactive or not exist).\n".encode())
                            else:
                                conn.sendall(b"ERROR: Invalid command. Use one of:\n"
                                             b"  - New Order: B <price> <qty> or S <price> <qty>\n"
                                             b"  - Cancel Order: CANCEL <order_id>\n"
                                             b"  - Edit Order: EDIT <order_id> <new_price> <new_quantity>\n")
                        except Exception as ex:
                            error_msg = f"ERROR: Exception while processing command '{line}': {ex}\n"
                            conn.sendall(error_msg.encode())
                            self.log.error(f"Error processing command from Client{client_id}: {line} | Exception: {ex}")
            except Exception as e:
                self.log.error(f"Error in client {client_id} handler: {e}")
