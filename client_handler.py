# client_handler.py
# Manages TCP client connections for order entry, modification, and cancellation.
# Each client has a dedicated thread and can submit text-based commands.
import socket                  # TCP socket API
import threading               # For spawning per-client threads
import logging                 # Logging client actions and errors
import config                  # TCP host/port configuration
from utils import enforce_tick # Normalize prices to valid ticks
import time                    # For simulated slippage delay
import random                  # Random sleep to model network/slippage variability

class ClientHandler:
    """
    Listens for incoming TCP connections from up to config.NUM_CLIENTS clients.
    Spawns a new thread per client to handle line-based commands:
      - New orders: "B <price> <qty>" or "S <price> <qty>"
      - Cancel orders: "CANCEL <order_id>"
      - Edit orders: "EDIT <order_id> <new_price> <new_quantity>"
      - Disconnect: "QUIT" or "EXIT"
    Sends back confirmations and errors over the same socket.
    """
    def __init__(self, matching_engine):
        # Reference to the central MatchingEngine instance
        self.engine = matching_engine

        # Set up TCP server socket
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Bind to configured host and port (e.g., "127.0.0.1", 50)
        self.server.bind((config.TCP_HOST, config.TCP_PORT))
        # Listen for incoming connections, up to config.NUM_CLIENTS queued
        self.server.listen(config.NUM_CLIENTS)

        # Logger for recording connection and command events
        self.log = logging.getLogger("exchange")

    def start(self):
        """
        Main loop: accept new client connections until the configured limit.
        For each client, launch _handle_client() in a daemon thread.
        """
        self.log.info("Waiting for client connections...")
        client_count = 0
        # Accept up to NUM_CLIENTS connections
        while client_count < config.NUM_CLIENTS:
            conn, addr = self.server.accept()
            client_count += 1
            self.log.info(f"Client {client_count} connected from {addr}")
            # Spawn thread to handle commands from this client
            thread = threading.Thread(
                target=self._handle_client,
                args=(conn, client_count),
                daemon=True
            )
            thread.start()

    def _handle_client(self, conn, client_id):
        """
        Dedicated per-client command loop:
          - Sends a welcome message with command syntax.
          - Reads lines, parses commands, and invokes matching_engine methods.
          - Simulates slippage delay on new orders.
          - Sends back ACKs, error messages, and trade confirmations.
        """
        with conn:
            # Send greeting and instructions
            welcome = (
                f"Welcome Client{client_id}! Connected to the exchange.\n"
                "Commands:\n"
                "  - New Order: B <price> <qty> or S <price> <qty>\n"
                "  - Cancel Order: CANCEL <order_id>\n"
                "  - Edit Order: EDIT <order_id> <new_price> <new_quantity>\n"
                "  - EXIT or QUIT to disconnect\n"
            )
            conn.sendall(welcome.encode())

            # Use file-like wrapper for line-buffered reading
            file_obj = conn.makefile('r')
            try:
                for line in file_obj:
                    line = line.strip()
                    if not line:
                        continue  # ignore empty lines
                    self.log.info(f"Client{client_id} sent: {line}")
                    parts = line.split()
                    cmd = parts[0].upper()

                    # Handle disconnect
                    if cmd in ("EXIT", "QUIT"):
                        conn.sendall(b"Goodbye!\n")
                        self.log.info(f"Client{client_id} requested disconnect.")
                        return

                    # New order: B or S plus price and quantity
                    elif cmd in ("B", "BUY", "S", "SELL") and len(parts) == 3:
                        # Simulate network/slippage delay up to CLIENT_SLIPPAGE_PERCENT secs
                        time.sleep(random.uniform(0, config.CLIENT_SLIPPAGE_PERCENT))

                        side = 'B' if cmd.startswith('B') else 'S'
                        try:
                            price = enforce_tick(float(parts[1]))
                            qty = int(parts[2])
                        except ValueError:
                            conn.sendall(b"ERROR: Invalid price or quantity format.\n")
                            continue

                        # Log receipt and forward to matching engine with `owner=conn` for confirmations
                        self.log.info(f"N: Received order from Client{client_id}: {side} {qty} @ {price:.2f}")
                        self.engine.process_order(side, price, qty, owner=conn)

                    # Cancel order: CANCEL <order_id>
                    elif cmd == "CANCEL" and len(parts) == 2:
                        try:
                            order_id = int(parts[1])
                        except ValueError:
                            conn.sendall(b"ERROR: Invalid order ID format.\n")
                            continue

                        self.log.info(f"Processing CANCEL command for order {order_id} from Client{client_id}")
                        success = self.engine.order_book.cancel_order(order_id)
                        if success:
                            ack = f"X: CANCEL ACK: Order {order_id} cancelled successfully.\n"
                            conn.sendall(ack.encode())
                            self.log.info(f"X: Client{client_id} cancelled order {order_id}")
                        else:
                            conn.sendall(
                                f"ERROR: Order {order_id} could not be cancelled or does not exist.\n".encode()
                            )

                    # Edit order: EDIT <order_id> <new_price> <new_quantity>
                    elif cmd == "EDIT" and len(parts) == 4:
                        try:
                            order_id = int(parts[1])
                            new_price = enforce_tick(float(parts[2]))
                            new_qty = int(parts[3])
                        except ValueError:
                            conn.sendall(b"ERROR: Invalid EDIT format. Use: EDIT <order_id> <new_price> <new_quantity>\n")
                            continue

                        self.log.info(
                            f"Processing EDIT command for order {order_id} from Client{client_id} "
                            f"to price {new_price:.2f} qty {new_qty}"
                        )
                        success = self.engine.order_book.edit_order(order_id, new_price=new_price, new_quantity=new_qty)
                        if success:
                            ack = f"M: EDIT ACK: Order {order_id} modified to price {new_price:.2f}, quantity {new_qty}.\n"
                            conn.sendall(ack.encode())
                            self.log.info(f"M: Client{client_id} edited order {order_id} to {new_price:.2f} @ {new_qty}")
                        else:
                            conn.sendall(
                                f"ERROR: Order {order_id} could not be edited (might be inactive or not exist).\n".encode()
                            )

                    # Unknown command
                    else:
                        conn.sendall(
                            b"ERROR: Invalid command. Use one of:\n"
                            b"  - New Order: B <price> <qty> or S <price> <qty>\n"
                            b"  - Cancel Order: CANCEL <order_id>\n"
                            b"  - Edit Order: EDIT <order_id> <new_price> <new_quantity>\n"
                        )
            except Exception as e:
                # Catch any unexpected errors per-client
                self.log.error(f"Error in client {client_id} handler: {e}")
