#!/usr/bin/env python3
"""
Grams Local mDNS Responder
==========================
Broadcasts and responds to mDNS queries for 'grams.local' on your home Wi-Fi network.
Allows all phones, tablets, and computers on the same Wi-Fi to open:
    http://grams.local
without typing IP addresses or port numbers!
"""

import socket
import struct
import time
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | [mDNS] %(message)s"
)
logger = logging.getLogger("mDNS_Broadcaster")

MCAST_GRP = "224.0.0.251"
MCAST_PORT = 5353
DOMAIN = "grams.local"

def get_local_ip():
    """Find the active local network IPv4 address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not actually connect, but gets the interface routing to LAN/Internet
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def build_response_packet(hostname: str, ip_str: str) -> bytes:
    """Build a standard DNS A-record response packet for mDNS."""
    # DNS Header: ID=0, Flags=0x8400 (Response, Authoritative), Questions=0, Answers=1, Auth=0, Additional=0
    header = struct.pack("!HHHHHH", 0, 0x8400, 0, 1, 0, 0)
    
    # QNAME encoding: e.g. 5'grams'5'local'0
    parts = hostname.strip(".").split(".")
    qname = b"".join(bytes([len(p)]) + p.encode("ascii") for p in parts) + b"\x00"
    
    # Answer Record: TYPE=1 (A), CLASS=0x8001 (IN + Flush Cache bit), TTL=120, RDLENGTH=4, RDATA=IP
    ip_bytes = socket.inet_aton(ip_str)
    answer = qname + struct.pack("!HHIH", 1, 0x8001, 120, 4) + ip_bytes
    return header + answer

def main():
    local_ip = get_local_ip()
    logger.info("Local IP detected: %s", local_ip)
    logger.info("Broadcasting '%s' -> %s on Wi-Fi...", DOMAIN, local_ip)

    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    
    # Allow multiple sockets to use the port
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass
    
    # Bind to mDNS port
    try:
        sock.bind(("", MCAST_PORT))
    except Exception as e:
        logger.error("Could not bind to port 5353: %s", e)
        sys.exit(1)

    # Join multicast group
    mreq = struct.pack("4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    except Exception as e:
        logger.warning("Multicast group join warning: %s", e)

    # Set multicast TTL and interface
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(local_ip))
    except Exception:
        pass

    resp_pkt = build_response_packet(DOMAIN, local_ip)

    # Send initial announcement
    try:
        sock.sendto(resp_pkt, (MCAST_GRP, MCAST_PORT))
        logger.info("Initial announcement sent! Try opening: http://%s in your browser.", DOMAIN)
    except Exception as e:
        logger.warning("Announcement error: %s", e)

    sock.settimeout(1.0)
    last_announce = time.time()

    while True:
        try:
            # Re-announce every 60 seconds
            if time.time() - last_announce > 60:
                sock.sendto(resp_pkt, (MCAST_GRP, MCAST_PORT))
                last_announce = time.time()

            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue

            # Check if query asks for 'grams' and 'local'
            if b"grams" in data.lower() and b"local" in data.lower():
                logger.info("Received mDNS query from %s:%s for '%s' — sending response!", addr[0], addr[1], DOMAIN)
                sock.sendto(resp_pkt, (MCAST_GRP, MCAST_PORT))
                # Also send direct unicast response
                sock.sendto(resp_pkt, addr)

        except KeyboardInterrupt:
            logger.info("mDNS Broadcaster stopped.")
            break
        except Exception as exc:
            logger.debug("Loop exception: %s", exc)

if __name__ == "__main__":
    main()
