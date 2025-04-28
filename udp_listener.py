# udp_listener.py
# Simple UDP multicast listener to receive and display exchange feed messages.
# Useful for debugging or monitoring the raw binary TBT-like feed on the network.

import socket    # Provides low-level network interface
import struct    # For unpacking binary data formats

# Multicast group and port must match those used in network.py
MCAST_GRP = '224.1.1.1'
MCAST_PORT = 5007

# Create a UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

# Allow multiple applications to bind to the same port (reuse address)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

# Bind to all interfaces on the multicast port
sock.bind(('', MCAST_PORT))

# Join the multicast group to receive its packets
# Pack group address and interface (INADDR_ANY) into '4sL' structure
mreq = struct.pack("4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

print(f"Listening for UDP multicast messages on {MCAST_GRP}:{MCAST_PORT}...")

# Continuously receive and print any incoming multicast packets
while True:
    data, addr = sock.recvfrom(1024)  # Buffer size up to 1024 bytes
    # Print sender address and raw data bytes
    print(f"Received from {addr}: {data}")
