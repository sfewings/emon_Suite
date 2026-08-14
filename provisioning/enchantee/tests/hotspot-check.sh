#!/bin/bash
# One-shot end-to-end check of hotspot mode, run detached because it drops the
# wireless link it would otherwise be reporting over.
#
# Returns wlan0 to the wifi profile on every exit path, including failure and
# SIGTERM. A separate timer (see the launcher) forces the same thing if this
# script dies outright, so the Pi cannot be stranded on its own hotspot.

LOG=${LOG:-/var/tmp/enchantee-hotspot-check.log}
exec >"$LOG" 2>&1

AP=enchantee
WIFI=netplan-wlan0-ZORAN
PASS=0; FAIL=0

say()  { printf '\n== %s\n' "$*"; }
ok()   { PASS=$((PASS+1)); printf '  PASS  %s\n' "$*"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n' "$*"; }
check(){ if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }

restore() {
    say "Restoring wifi profile '$WIFI'"
    nmcli connection up "$WIFI" >/dev/null 2>&1
    for _ in $(seq 40); do
        [ "$(enchantee-mode current)" = wifi ] && break
        sleep 1
    done
    printf '  mode now: %s   wlan0: %s\n' \
        "$(enchantee-mode current)" "$(ip -4 -br addr show wlan0 | awk '{print $3}')"
    # enchantee-mode records intent; put the remembered mode back to wifi so a
    # reboot after this test does not come up on the hotspot.
    echo wifi > /var/lib/enchantee/mode
    printf '\n== Result: %d passed, %d failed\n' "$PASS" "$FAIL"
}
trap restore EXIT

# Minimal A-record query straight at a chosen server. There is no dig or
# nslookup on this image, and getent would consult the local resolver instead of
# the DNS server we actually want to test.
dnsq() {
python3 - "$1" "$2" <<'PY'
import socket, struct, sys, random
server, name = sys.argv[1], sys.argv[2]
qid = random.randint(0, 0xffff)
q = struct.pack('!HHHHHH', qid, 0x0100, 1, 0, 0, 0)
for label in name.split('.'):
    q += bytes([len(label)]) + label.encode()
q += b'\x00' + struct.pack('!HH', 1, 1)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(5)
try:
    s.sendto(q, (server, 53))
    data, _ = s.recvfrom(512)
except Exception as e:
    print(f"NOANSWER {e}"); sys.exit(1)
ancount = struct.unpack('!H', data[6:8])[0]
if not ancount:
    print("NOANSWER rcode=%d" % (data[3] & 0xf)); sys.exit(1)
i = 12
while data[i]: i += data[i] + 1
i += 5
for _ in range(ancount):
    if data[i] & 0xc0 == 0xc0: i += 2
    else:
        while data[i]: i += data[i] + 1
        i += 1
    rtype, _, _, rdlen = struct.unpack('!HHIH', data[i:i+10]); i += 10
    if rtype == 1:
        print(socket.inet_ntoa(data[i:i+4])); sys.exit(0)
    i += rdlen
print("NOANSWER no A record"); sys.exit(1)
PY
}

say "Before: mode=$(enchantee-mode current) wlan0=$(ip -4 -br addr show wlan0 | awk '{print $3}')"

say "Switching to hotspot '$AP'"
nmcli connection up "$AP" >/dev/null 2>&1
for _ in $(seq 45); do
    [ "$(enchantee-mode current)" = ap ] && break
    sleep 1
done

say "1. Mode and radio"
check "enchantee-mode reports ap"        '[ "$(enchantee-mode current)" = ap ]'
check "wlan0 is in AP mode"              'iw dev wlan0 info | grep -q "type AP"'
check "SSID is Enchantee"                'iw dev wlan0 info | grep -qi "ssid Enchantee"'
check "wlan0 holds 10.42.0.1"            'ip -4 addr show wlan0 | grep -q "10.42.0.1/24"'
iw dev wlan0 info 2>/dev/null | sed 's/^/    /'

say "2. NetworkManager's dnsmasq"
check "dnsmasq running for shared conn"  'pgrep -af "dnsmasq.*NetworkManager" >/dev/null'
check "our conf dir is in use"           'pgrep -af dnsmasq | grep -q dnsmasq-shared'
pgrep -af dnsmasq 2>/dev/null | sed 's/^/    /'

say "3. Name resolution (the Android / unicast-DNS path)"
res=$(dnsq 10.42.0.1 enchantee.local)
printf '    dnsq 10.42.0.1 enchantee.local -> %s\n' "$res"
if [ "$res" = "10.42.0.1" ]; then ok "dnsmasq answers enchantee.local as 10.42.0.1"
else bad "dnsmasq answered '$res', expected 10.42.0.1"; fi

say "4. avahi / mDNS"
check "avahi running"                    'systemctl is-active --quiet avahi-daemon'
check "avahi published 10.42.0.1"        'journalctl -u avahi-daemon -b --no-pager | grep -q "record for 10.42.0.1 on wlan0"'
journalctl -u avahi-daemon -b --no-pager 2>/dev/null | grep -E 'record for .* on wlan0|Host name is' | tail -3 | sed 's/^/    /'

say "4b. mDNS answered on the wire (what a client actually does)"
# avahi re-probes and re-announces after the address change, and will not answer
# authoritatively until that settles. Retry rather than sampling once.
for attempt in $(seq 12); do
    mres=$(python3 "$(dirname "$0")"/mdnsq.py enchantee.local 2>&1 | tail -1)
    case "$mres" in 10.42.0.1*) break ;; esac
    sleep 3
done
printf '    mdns enchantee.local -> %s  (after %s attempt(s), ~%ss)\n' "$mres" "$attempt" "$(( (attempt-1)*3 ))"
case "$mres" in
    10.42.0.1*) ok "avahi answers enchantee.local as 10.42.0.1 over multicast" ;;
    *)          bad "avahi answered '$mres', expected 10.42.0.1" ;;
esac
check "hostname is enchantee"            '[ "$(hostnamectl --static)" = enchantee ]'

say "5. NAT and DHCP for clients"
check "DHCP range configured"            'pgrep -af dnsmasq | grep -q "dhcp-range=10.42.0"'
check "masquerade rule present"          'nft list ruleset 2>/dev/null | grep -q masquerade || iptables -t nat -S 2>/dev/null | grep -q MASQUERADE'
check "ip forwarding enabled"            '[ "$(sysctl -n net.ipv4.ip_forward)" = 1 ]'

say "6. Services over the hotspot address"
for u in / /nodered/ /grafana/ /portainer/ /events/ /settings/; do
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 15 "http://10.42.0.1$u")
    if [ "$code" = 200 ]; then ok "http://10.42.0.1$u -> 200"; else bad "http://10.42.0.1$u -> $code"; fi
done

say "7. Services by name, as a client would reach them"
for u in / /grafana/ /events/; do
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 15 "http://enchantee.local$u")
    if [ "$code" = 200 ]; then ok "http://enchantee.local$u -> 200"; else bad "http://enchantee.local$u -> $code"; fi
done

say "Checks complete"
