#!/usr/bin/env python

import socket
from icmplib import ping
from string import hexdigits

broadcast = "192.168.1.255"
port = 9


def power(host, mac_address, broadcast=broadcast, port=port):
    mac_address = ''.join(c for c in mac_address if c in hexdigits)
    target = bytes.fromhex('ff' * 6 + mac_address * 16)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(target, (broadcast, port))
        return True
    except socket.error:
        return False


def status(host, mac_address, count=1, timeout=0.1):
    return ping(host, count=count, timeout=timeout).is_alive
