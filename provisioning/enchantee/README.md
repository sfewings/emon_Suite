# Enchantee provisioning

Installation guide for the Enchantee Raspberry Pi. This is the enchantee
equivalent of [`LinuxInstall/InstallationGuideFor RaspPi-Readme.txt`](../../LinuxInstall/InstallationGuideFor%20RaspPi-Readme.txt),
which covers the shannstainable provision.

Baseline this was written against:

| | |
|---|---|
| Board | Raspberry Pi 5 |
| OS | Debian 13 (trixie), 64-bit |
| Network stack | NetworkManager 1.52 (**not** dhcpcd/hostapd) |
| Hostname | `enchantee` |
| Web server | nginx 1.26 |
| Containers | docker + compose, see [`docker-compose.yml`](docker-compose.yml) |

Everything under [`etc/`](etc/) and [`usr/`](usr/) in this directory mirrors its
real path on the Pi, so each file can be copied straight to its destination.
See [File manifest](#file-manifest) for the full list.

---

## 1. Base Raspberry Pi setup

Steps 1-8 of the shannstainable guide apply unchanged and are not repeated here:
git, SSH keys, the `/share` directory, cloning `emon_Suite`, samba, and docker.
Follow [`LinuxInstall/InstallationGuideFor RaspPi-Readme.txt`](../../LinuxInstall/InstallationGuideFor%20RaspPi-Readme.txt)
up to and including the docker install, then come back here.

---

## 2. Serial port for the Moteino emon receiver

In `/boot/firmware/config.txt`:

```
enable_uart=1
```

On a Pi 4 also reassign Bluetooth to the mini-UART (not needed on Pi 5):

```
dtoverlay=miniuart-bt
```

Wiring:

| Moteino | Raspberry Pi |
|---|---|
| TX | RX, GPIO15 |
| RX | TX, GPIO14 |
| GND | GND |

The port appears as `/dev/ttyAMA0`, which is what `emon_serial_to_mqtt` is
pointed at in [`docker-compose.yml`](docker-compose.yml).

Disable the serial console so it does not fight the Moteino for the port:
`sudo raspi-config` → *3 Interface Options* → *P6 Serial Port* → login shell
**No**, port hardware **Yes**.

---

## 3. Waveshare LCD panel

In `/boot/firmware/config.txt`:

```
dtoverlay=vc4-kms-v3d
dtoverlay=vc4-kms-dsi-waveshare-panel,8_0_inch
```

---

## 4. GPS and gpsd

Following <https://robrobinette.com/pi_GPS_PPS_Time_Server.htm>.

In `/boot/firmware/config.txt`:

```
# Enable uart 5 for the GPS module. Note: pin assignments differ Pi 4 vs Pi 5.
# GPIO12=tx, GPIO13=rx, /dev/ttyAMA5
dtoverlay=uart5
# Listen for the GPS PPS signal on gpio18
dtoverlay=pps-gpio,gpiopin=18
```

In `/etc/modules`:

```
pps-gpio
```

Install and configure:

```bash
sudo apt install gpsd gpsd-clients
```

In `/etc/default/gpsd`:

```
DEVICES="/dev/ttyAMA5 /dev/pps0"
GPSD_OPTIONS="-n"
START_DAEMON="true"
USBAUTO="false"
```

```bash
sudo systemctl enable gpsd
sudo systemctl restart gpsd
```

The `emon_gpsd_to_mqtt` container runs with `network_mode: host` so it can reach
gpsd on localhost.

---

## 5. GPS-disciplined clock with chrony

From <https://www.workswiththeweb.com/piprojects/2023/08/06/RBPi-NTP-Server/>.

```bash
sudo apt install chrony
```

Append to `/etc/chrony/chrony.conf`:

```
local stratum 10
refclock SHM 0 poll 3 refid GPS1
refclock PPS /dev/pps0 lock GPS1 refid GPS prefer
```

```bash
sudo systemctl restart chrony
chronyc -n sourcestats    # verify
```

This matters offline: with no internet the Pi has no NTP, and the emon log
filenames and influx timestamps depend on the clock being right.

---

## 6. Docker stack

```bash
cd /share/emon_Suite/provisioning/enchantee
docker compose up -d
```

Create the environment file first and fill in the credentials:

```bash
cp .env.example .env
```

`.env` is gitignored; [`.env.example`](.env.example) is the committed template.
Services:

| Container | Image | Host port | Reached at |
|---|---|---|---|
| `node_red` | nodered/node-red | 1880 | `/` and `/nodered/` |
| `grafana1` | grafana/grafana | 3000 | `/grafana/` |
| `portainer` | portainer/portainer-ce | 9000, 9443 | `/portainer/` |
| `emon_settings_web` | sfewings32/emon_settings_web | 5001 | `/settings/` |
| `influx` | arm32v7/influxdb | 8086 | direct |
| `mqtt` | eclipse-mosquitto | 1883 | direct |
| `emon_serial`, `emon_gpsd`, `emon_log`, `emon_influx`, `emon_logtojson`, `event_recorder` | | | no HTTP |

Two settings in `docker-compose.yml` exist purely to make the reverse proxy
work, and are explained in [section 7.4](#74-grafana-under-grafana) and
[7.5](#75-portainer-under-portainer):

```yaml
grafana:
  environment:
    - GF_SERVER_SERVE_FROM_SUB_PATH=true
    - GF_SERVER_ROOT_URL=${GRAFANA_URL}      # %(protocol)s://%(domain)s/grafana/
    - GF_SERVER_DOMAIN=${DOMAIN_NAME}        # enchantee.local

portainer:
  command: --base-url=/portainer
```

---

## 7. Networking: one address for every service

### 7.1 What this is trying to achieve

The Pi has to work in two situations, and the URLs should not change between
them:

* **Joined to a wifi network** (a house network, a marina, a phone hotspot).
  The Pi is a normal DHCP client.
* **Running its own hotspot**, SSID `Enchantee`, when there is no network to
  join. The Pi is the AP, the router, the DHCP server and the DNS server.

Only one of the two runs at a time. `wlan0` cannot be an access point and a
client simultaneously in any reliable way, so the modes are switched with
[`enchantee-mode`](usr/local/bin/enchantee-mode) from a shell (section 7.8) or
the desktop launcher (section 7.9).

### 7.2 How the name resolves

There is exactly one name to remember: **`enchantee.local`**. It works in both
modes, and the raw IP always works as a fallback.

| | Hotspot mode | Joined to a wifi network |
|---|---|---|
| `enchantee.local` | ✅ mDNS, plus unicast DNS from the Pi's own dnsmasq | ✅ mDNS |
| IP address | ✅ `10.42.0.1` | ✅ whatever DHCP handed out |

`.local` is the mDNS domain. Nothing on the network has to know about it: the Pi
answers for itself over multicast, which is why the same name works on a home
network, a marina wifi and the Pi's own hotspot without any router
configuration. avahi provides this (section 7.6).

The wrinkle is that mDNS *hostname* resolution is unreliable on Android. Service
discovery works there, but resolving `foo.local` through the system resolver and
Chrome has been inconsistent for years and still varies by device and version.
Anything that only speaks unicast DNS has the same problem: minimal containers,
some embedded clients, older Windows.

In hotspot mode that is covered, because the Pi is also the DNS server for its
clients and answers `enchantee.local` over ordinary DNS as well (section 7.7).
Clients that resolve `.local` by multicast never ask dnsmasq, so the two paths
do not conflict, and every client is served by one or the other.

On someone else's wifi it is not covered, because nothing there answers for the
name. **Accepted limitation:** an Android device on the house wifi cannot reach
the Pi by name and needs the IP address. On a network you control, fix it with a
DHCP reservation plus a static DNS entry pointing `enchantee.local` at the
reserved address.

One client-side setting defeats all of this: Android's **Private DNS** in strict
mode (*Settings → Network → Private DNS → a specific hostname*) bypasses the
local resolver entirely, so no name the Pi serves will resolve, and DNS breaks
altogether once the hotspot has no internet. Set it to *Off* or *Automatic*.

An earlier revision of this setup also served `enchantee.lan`. It was dropped:
it only ever worked in hotspot mode, and having dnsmasq answer `enchantee.local`
covers that case better with one name instead of two.

### 7.3 nginx reverse proxy

nginx on port 80 is the single front door. Install and place the config:

```bash
sudo apt install nginx
cd /share/emon_Suite/provisioning/enchantee
sudo cp etc/nginx/conf.d/upgrade-map.conf     /etc/nginx/conf.d/upgrade-map.conf
sudo cp etc/nginx/sites-available/default     /etc/nginx/sites-available/default
sudo nginx -t && sudo systemctl reload nginx
```

`default` is already symlinked from `sites-enabled/` on a stock nginx install,
so there is no new site to enable.

Routes, from [`etc/nginx/sites-available/default`](etc/nginx/sites-available/default):

| URL | Backend |
|---|---|
| `/` | Node-RED dashboard, `:1880/ui/` |
| `/nodered/` | Node-RED flow editor, `:1880/` |
| `/grafana/` | Grafana, `:3000` |
| `/portainer/` | Portainer, `:9000` |
| `/settings/` | emon settings web, `:5001` |

The server block uses `server_name _` as the sole `default_server`. That is
deliberate: it answers to `enchantee.local`, `10.42.0.1` and whatever DHCP
address the Pi holds, all with the same routes, so nothing has to be
reconfigured when the mode changes. nginx never matches on the hostname, which
is why changing the naming scheme does not touch this file at all.

[`upgrade-map.conf`](etc/nginx/conf.d/upgrade-map.conf) defines
`$connection_upgrade`, which sends `Connection: upgrade` only when the client
actually requested a WebSocket and `Connection: close` otherwise. Hardcoding
`Connection "upgrade"` on every location, as the earlier config did, sets the
header on ordinary requests too.

Node-RED dashboard 1.x (`node-red-dashboard` 3.x) emits **relative** asset paths
(`css/app.min.css`, `socket.io/socket.io.js`), with no `<base href>`. That is
why mapping the site root onto `/ui/` works: the browser asks for
`/css/app.min.css` and nginx forwards it to `:1880/ui/css/app.min.css`. Dashboard
2.0 behaves differently and this location would need revisiting.

### 7.4 Grafana under `/grafana/`

With `GF_SERVER_SERVE_FROM_SUB_PATH=true`, Grafana serves the app **including**
the `/grafana` prefix and emits `<base href="/grafana/">`. nginx must therefore
pass the path through untouched:

```nginx
location /grafana/ {
    proxy_pass http://127.0.0.1:3000;    # no trailing URI, no rewrite
}
```

A `proxy_pass http://127.0.0.1:3000/;` (trailing slash) or a
`rewrite ^/grafana/(.*) /$1 break;` strips the prefix and Grafana then 404s or
redirect-loops. Both appear in older copies of this config; neither is correct
alongside `serve_from_sub_path`.

Grafana Live (streaming panels) is a WebSocket and gets its own location block
with the upgrade headers.

`GF_SERVER_ROOT_URL` only affects absolute links Grafana generates itself, such
as alert notifications and share URLs. Assets are relative under
`serve_from_sub_path`, so the box stays reachable by IP, and by `10.42.0.1` in
hotspot mode, even though `DOMAIN_NAME` pins one name.

Check it after a change:

```bash
curl -s http://enchantee.local/grafana/ | grep -o '<base[^>]*>'
# <base href="/grafana/" />
```

### 7.5 Portainer under `/portainer/`

Portainer is the exact opposite of Grafana and this is easy to get backwards.
`--base-url=/portainer` sets the cookie path and the URLs Portainer generates,
but the HTTP server still routes at its own root: `:9000/portainer/` returns
404. So nginx **must** strip the prefix:

```nginx
location /portainer/ {
    proxy_pass http://127.0.0.1:9000/;   # trailing slash strips /portainer
}
```

The front end sets its own `<base href>` at runtime from
`window.location.pathname`, and it hash-routes (`#!/...`), so deep links stay
under `/portainer/` and keep resolving. `proxy_read_timeout` is raised to an
hour so console exec and log streaming do not get cut off.

Verified with (2.33.6):

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://enchantee.local/portainer/
curl -s http://enchantee.local/portainer/api/system/status
```

### 7.6 mDNS: `enchantee.local`

`avahi-daemon` ships enabled on Debian. It publishes `<hostname>.local`, so the
name follows the hostname:

```bash
sudo hostnamectl set-hostname enchantee
```

Also set the `127.0.1.1` line in `/etc/hosts` to `127.0.1.1 enchantee` and
append the block in [`etc/hosts.append`](etc/hosts.append). That points
`enchantee.local` at loopback for requests originating on the Pi itself, so
local checks keep working even if avahi is down. It shadows the mDNS answer
locally, which is what you want for a request that never leaves the box.

One change to [`etc/avahi/avahi-daemon.conf`](etc/avahi/avahi-daemon.conf) is
needed:

```ini
[server]
allow-interfaces=wlan0
```

Without it avahi advertises every address on the box, which on a docker host
means `docker0`, each `br-*` and every `veth*`. Clients then get answers like
`172.18.0.1` for `enchantee.local`, and the veth set changes on every container
restart. Restricting avahi to `wlan0` publishes exactly one usable address, and
`wlan0` is the right interface in both hotspot and client mode.

```bash
sudo cp etc/avahi/avahi-daemon.conf /etc/avahi/avahi-daemon.conf
sudo systemctl restart avahi-daemon
getent ahostsv4 enchantee.local      # should be the wlan0 address, not 172.x
```

### 7.7 The `Enchantee` hotspot

The hotspot is a NetworkManager profile, not hostapd. NetworkManager starts
wpa_supplicant in AP mode and, because `ipv4.method` is `shared`, also brings up
its own dnsmasq for DHCP and DNS plus NAT via nftables. `dnsmasq-base` is the
only extra package, and it is usually already installed.

Create the profile (the PSK is not stored in this repo):

```bash
sudo nmcli connection add type wifi ifname wlan0 con-name enchantee \
    ssid Enchantee autoconnect no \
    802-11-wireless.mode ap \
    802-11-wireless-security.key-mgmt wpa-psk \
    802-11-wireless-security.psk 'YOUR-HOTSPOT-PASSWORD' \
    ipv4.method shared ipv4.addresses 10.42.0.1/24
```

[`etc/NetworkManager/system-connections/enchantee.nmconnection.example`](etc/NetworkManager/system-connections/enchantee.nmconnection.example)
is the resulting file for reference, with the PSK removed. If you install it
directly instead of using `nmcli`, it must be `root:root` mode `600` or
NetworkManager ignores it.

`ipv4.addresses` is pinned rather than left to NetworkManager's default so the
address in the dnsmasq config below cannot drift.

`autoconnect no` keeps the Pi joining wifi by preference; the hotspot only comes
up when asked for.

Then give hotspot clients the name over unicast DNS as well as mDNS:

```bash
sudo cp etc/NetworkManager/dnsmasq-shared.d/enchantee.conf \
        /etc/NetworkManager/dnsmasq-shared.d/enchantee.conf
```

[That file](etc/NetworkManager/dnsmasq-shared.d/enchantee.conf) is read by the
dnsmasq instance NetworkManager starts for a `shared` connection. Its one line
maps `enchantee.local` to `10.42.0.1`.

That looks redundant next to avahi, and for iOS, macOS, Windows and Linux it is:
those resolve `.local` by multicast and never ask dnsmasq. It exists for clients
that send `.local` to the configured resolver instead, Android above all, whose
mDNS hostname resolution cannot be relied on. Between the two paths every
hotspot client can resolve the name. RFC 6762 reserves `.local` for mDNS, so
answering it over unicast DNS is a deliberate bend of the rule; it is safe here
because only clients that were going to fail ever see the answer.

The address must match `ipv4.addresses` on the profile above. Syntax-check the
file before switching modes:

```bash
dnsmasq --test --conf-file=/etc/NetworkManager/dnsmasq-shared.d/enchantee.conf
```

### 7.8 Switching modes from the command line

```bash
sudo install -m 755 usr/local/bin/enchantee-mode /usr/local/bin/enchantee-mode
```

```
enchantee-mode status         # which mode is active, and the URL to use
enchantee-mode current        # just ap | wifi | none, for scripts
sudo enchantee-mode toggle    # switch to whichever mode is not active
sudo enchantee-mode ap        # start the Enchantee hotspot
sudo enchantee-mode wifi [SSID]
```

`status` and `current` work as any user; bringing a profile up needs root.

Switching drops the wireless link, which over SSH means dropping the session
that issued the command. The script hands the `nmcli` call to `systemd-run` so
the switch completes after the ssh connection dies with it. That also makes the
call asynchronous: it returns before the new mode is up, so poll `current` if
you need to know when the switch has landed.

With no SSID given, `wifi` returns to the infrastructure profile with the most
recent `TIMESTAMP`, so toggling off the hotspot rejoins the network you actually
came from rather than a hardcoded one. `FALLBACK_WIFI` in the script is only
used when nothing has ever connected.

The wifi profiles themselves are managed by netplan on this image
(`/etc/netplan/90-NM-*.yaml`), so add new networks with `nmcli device wifi
connect` rather than hand-editing NetworkManager files.

### 7.9 Switching modes from the desktop

A launcher on the Pi's own screen, for when there is no keyboard: one icon that
flips to whichever mode is not currently active.

```bash
sudo install -m 755 usr/local/bin/enchantee-mode-gui /usr/local/bin/enchantee-mode-gui
install -m 755 home/pi/Desktop/Enchantee-Wifi-Mode.desktop /home/pi/Desktop/
install -m 644 home/pi/Desktop/Enchantee-Wifi-Mode.desktop /home/pi/.local/share/applications/
```

The `Desktop` copy is the icon; the `applications` copy puts it in the
Preferences menu as well. Both need `zenity`, which is already installed on
Raspberry Pi OS.

[`enchantee-mode-gui`](usr/local/bin/enchantee-mode-gui) asks for confirmation
before doing anything, because switching drops the network and a stray tap on a
touchscreen should not take it down. It then calls `sudo enchantee-mode toggle`
and **polls until the new mode is actually up**, so the dialog reports what
happened rather than what was requested, and a failed switch is reported as a
failure rather than silently looking like success.

The dialogs run as the desktop user and only the switch goes through `sudo`.
That needs no password because Raspberry Pi OS ships
`/etc/sudoers.d/010_pi-nopasswd`. On an image without it, add:

```
pi ALL=(ALL) NOPASSWD: /usr/local/bin/enchantee-mode
```

Doing it through `sudo` rather than letting NetworkManager's own polkit rules
handle it is deliberate: `org.freedesktop.NetworkManager.wifi.share.protected`,
which a WPA-protected shared connection needs, is denied to ordinary users on
this image, so an unprivileged `nmcli connection up enchantee` fails.

---

## 8. Node-RED dashboard on the local display

Open `http://localhost:1880/ui` in a browser and make a desktop shortcut.

Stop the file manager prompting about executable text files: File Explorer →
*Edit → Preferences → General* → uncheck *Ask what to do with executable text
files*, and *Edit → Preferences → Advanced* → uncheck *Use Application Startup
Notify by default*.

Autostart it with the desktop:

```bash
mkdir -p /home/pi/.config/autostart
# copy Enchantee.desktop into /home/pi/.config/autostart/
```

If the keyring prompt appears ("The application wants access to keyring
'Default keyring' but it is locked"), reset it to a blank password:

```bash
mv ~/.local/share/keyrings/Default_Keyring.keyring ~/.local/share/keyrings/old_Default_Keyring.keyring
# reboot, set a blank password, ignore the warning
```

---

## File manifest

Copy each to the path its directory mirrors.

| In this repo | On the Pi | Notes |
|---|---|---|
| [`etc/nginx/sites-available/default`](etc/nginx/sites-available/default) | `/etc/nginx/sites-available/default` | already symlinked from `sites-enabled/` |
| [`etc/nginx/conf.d/upgrade-map.conf`](etc/nginx/conf.d/upgrade-map.conf) | `/etc/nginx/conf.d/upgrade-map.conf` | `$connection_upgrade` map |
| [`etc/avahi/avahi-daemon.conf`](etc/avahi/avahi-daemon.conf) | `/etc/avahi/avahi-daemon.conf` | adds `allow-interfaces=wlan0` |
| [`etc/NetworkManager/dnsmasq-shared.d/enchantee.conf`](etc/NetworkManager/dnsmasq-shared.d/enchantee.conf) | `/etc/NetworkManager/dnsmasq-shared.d/enchantee.conf` | hotspot DNS |
| [`etc/NetworkManager/system-connections/enchantee.nmconnection.example`](etc/NetworkManager/system-connections/enchantee.nmconnection.example) | `/etc/NetworkManager/system-connections/enchantee.nmconnection` | reference only, PSK removed, `root:root` `600` |
| [`etc/hosts.append`](etc/hosts.append) | append to `/etc/hosts` | on-Pi resolution of `enchantee.local` |
| [`usr/local/bin/enchantee-mode`](usr/local/bin/enchantee-mode) | `/usr/local/bin/enchantee-mode` | mode 755 |
| [`usr/local/bin/enchantee-mode-gui`](usr/local/bin/enchantee-mode-gui) | `/usr/local/bin/enchantee-mode-gui` | mode 755, needs zenity |
| [`home/pi/Desktop/Enchantee-Wifi-Mode.desktop`](home/pi/Desktop/Enchantee-Wifi-Mode.desktop) | `/home/pi/Desktop/` and `/home/pi/.local/share/applications/` | mode 755 on the Desktop copy |
| [`docker-compose.yml`](docker-compose.yml) | run from this directory | |
| [`.env.example`](.env.example) | copy to `.env` alongside the compose file | credentials, `DOMAIN_NAME`, `GRAFANA_URL`; `.env` is gitignored |
| [`emon_config/`](emon_config/) | mounted into the emon containers | |
| [`mosquitto-config/`](mosquitto-config/) | mounted into `mqtt` | |
| [`grafana-provisioning/`](grafana-provisioning/) | mounted into `grafana1` | dashboards and datasource |

Changes that are commands rather than files: the hostname
(`hostnamectl set-hostname enchantee`), the `127.0.1.1` line in `/etc/hosts`,
and the `enchantee` NetworkManager profile.

---

## Verification

From the Pi, on either mode:

```bash
for u in / /nodered/ /grafana/ /portainer/ /settings/; do
    printf '%-12s ' "$u"
    curl -s -o /dev/null -w '%{http_code}\n' -m 10 "http://enchantee.local$u"
done
```

`/`, `/nodered/`, `/grafana/` and `/portainer/` should be `200`.

`/settings/` currently returns `000` (timeout), and the fault is in the
`emon_settings_web` container rather than in nginx: gunicorn logs that it is
listening on `:5000`, and the socket accepts, but no response is ever sent, so
the container's own healthcheck fails too and it sits `unhealthy`. Reproduce
past nginx with `curl -m 5 http://localhost:5001/`. The proxy route is
configured and correct, and will work once the app does.

Then from a phone or laptop, <http://enchantee.local/> in both modes: joined to
wifi, and again after `enchantee-mode ap` and joining SSID `Enchantee`.

Test with an Android device too if you have one, since it is the client that
exercises the unicast-DNS path rather than mDNS. If it fails, check *Settings →
Network → Private DNS* is not set to a specific hostname.

```bash
enchantee-mode status        # confirms mode and prints the URL
```

---

## Gotchas

**Grafana and Portainer need opposite nginx treatment.** Grafana wants the
`/grafana` prefix forwarded; Portainer wants `/portainer` stripped. Getting
either backwards produces a 404 or a blank page with broken assets. See
sections [7.4](#74-grafana-under-grafana) and [7.5](#75-portainer-under-portainer).

**Android cannot be relied on to resolve `.local` by mDNS.** In hotspot mode
that is handled, because the Pi's dnsmasq answers the name over unicast DNS as
well. On someone else's wifi an Android client needs the IP address. Android's
Private DNS in strict mode breaks name resolution in both modes. See
[7.2](#72-how-the-name-resolves).

**avahi on a docker host over-advertises.** Without `allow-interfaces=wlan0` it
hands out container bridge addresses for `enchantee.local`. See [7.6](#76-mdns-enchanteelocal).

**Switching mode kills your SSH session.** `enchantee-mode` detaches the
`nmcli` call so the switch itself survives, but the shell will not.

**This provision does not use hostapd or a standalone dnsmasq.** Earlier
revisions of this directory documented a `hostapd` + `/etc/dnsmasq.d/` setup on
`192.168.4.1` with services at `/display` and `/upload`. That was never
deployed and has been removed; NetworkManager provides the equivalent with
fewer moving parts. Check `git log` for the old files if needed.

**Credentials live in `.env`, which is gitignored.** Commit
[`.env.example`](.env.example) instead, with placeholders. Do not put the
hotspot PSK in either file; it is set on the Pi with `nmcli` (section 7.7).

**`.env` was tracked until now, so its real credentials are in this repo's
history** and reachable from the GitHub remote. Untracking it stops further
exposure but does not remove what is already committed. Anything that was in it
should be treated as compromised and rotated: the InfluxDB and Grafana admin
passwords, the MySQL passwords, the WordPress application password, and the
credentials embedded in `WP_WHITELIST_ENDPOINT`. The same applies to the other
provisions, whose `.env` files are still tracked.
