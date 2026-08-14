#!/usr/bin/env python3
"""Ask for a name over real multicast DNS and print the A record returned.

Needed because there is no avahi-resolve on this image, and getent would be
answered by the /etc/hosts entry rather than by avahi on the wire. This sends a
genuine query to 224.0.0.251:5353, which is exactly what a client device does.
"""
import socket, struct, sys

name = sys.argv[1] if len(sys.argv) > 1 else "enchantee.local"

q = struct.pack('!HHHHHH', 0, 0, 1, 0, 0, 0)
for label in name.split('.'):
    q += bytes([len(label)]) + label.encode()
q += b'\x00' + struct.pack('!HH', 1, 1)          # QTYPE=A, QCLASS=IN

def iface_ip(dev='wlan0'):
    import fcntl
    sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        return socket.inet_ntoa(fcntl.ioctl(
            sk.fileno(), 0x8915, struct.pack('256s', dev[:15].encode()))[20:24])
    finally:
        sk.close()

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
# Pin the outbound interface. In hotspot mode the Pi is the gateway and has no
# default route, so an unbound socket has nothing to send multicast from and
# sendto() fails with ENETUNREACH.
local = iface_ip('wlan0')
s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(local))
s.bind((local, 0))
s.settimeout(4)
s.sendto(q, ('224.0.0.251', 5353))

try:
    while True:
        data, addr = s.recvfrom(2048)
        if struct.unpack('!H', data[6:8])[0] == 0:
            continue                              # our own query echoed back
        i = 12
        while data[i]:
            i += data[i] + 1
        i += 5
        for _ in range(struct.unpack('!H', data[6:8])[0]):
            if data[i] & 0xc0 == 0xc0:
                i += 2
            else:
                while data[i]:
                    i += data[i] + 1
                i += 1
            rtype, _, _, rdlen = struct.unpack('!HHIH', data[i:i + 10])
            i += 10
            if rtype == 1:
                print(f"{socket.inet_ntoa(data[i:i+4])} (from {addr[0]})")
                sys.exit(0)
            i += rdlen
except socket.timeout:
    print("NOANSWER")
    sys.exit(1)
