*Enchantee installation instructions
===============================

**Enable serial port for Moteino emon input
------------------------------
in /boot/firmware/config.txt add:
```enable_uart=1```
reassign Bluetooth to use mini-UART: (Raspberry Pi 4 only )
```dtoverlay=miniuart-bt```
Connect Moteino to Raspberry Pi UART:
Moteino TX -> Pi RX (GPIO15)
Moteino RX -> Pi TX (GPIO14)
Moteino GND -> Pi GND  
UART can be accessed using ttyAMA0


**To enable Waveshare LCD display
------------------------------
'''dtoverlay=vc4-kms-v3d'''
'''dtoverlay=vc4-kms-dsi-waveshare-panel,8_0_inch'''


To install GPS and GPSD
------------------------------
Follow instructions at https://robrobinette.com/pi_GPS_PPS_Time_Server.htm
Add to /boot/firmware/config.txt:

```# Enable uart 5 for GPS module. Note: some confusion on pins for Raspberry Pi 4 vs Raspberry Pi 5``` 
```#GPIO12=tx, GPIO13=rx,/dev/ttyAMA5```
```dtoverlay=uart5```
```# Listen for the GPS PPS signal on gpio18```
```dtoverlay=pps-gpio,gpiopin=18```
 
Add to /etc/modules:
```pps-gpio```

install gpsd and gpsd-clients:
```sudo apt install gpsd gpsd-clients```

Add to /etc/default/gpsd:
```DEVICES="/dev/ttyAMA5 /dev/pps0"```
```GPSD_OPTIONS="-n"```
```START_DAEMON="true"```
```USBAUTO="false"```

Restart gpsd:
```sudo systemctl enable gpsd```
```sudo systemctl restart gpsd```

Install chrony to use GPS time. As from https://www.workswiththeweb.com/piprojects/2023/08/06/RBPi-NTP-Server/
------------------------------
```sudo apt install chrony```
Add to /etc/chrony/chrony.conf:
```local stratum 10```
```refclock SHM 0 poll 3 refid GPS1```
```refclock PPS /dev/pps0 lock GPS1 refid GPS prefer```
Restart chrony:
```sudo systemctl restart chrony```
Test it is working:
```chronyc -n sourcestats```

Starting an instance of nodered UI when RaspPi Starts up
-------------------------------
Create a shortcut to start
```Open localhost:1880:ui in a web browser and create a shortcut to the desktop.```
Setup file explorer not display "This text file seems to be an executable script. What do you want to do?"
```In File Explorer, uncheck these options:```
```[Edit] --> [Preferences] --> [General]........ [ ] "Ask what to do with executable text files"```
```[Edit] --> [Preferences] --> [Advanced]........ [ ] Use Application Startup Notify by default```
Make the script run when the desktop starts up. This is done by creating a .desktop file in ~/.config/autostart/ that points to the script. For example, create a file called start_nodered.desktop with the following content:
```mkdir -p /home/pi/.config/autostart```
```Move Enchantee.desktop to /home/pi/.config/autostart/```
Stop "The application wants access to keyring "Default keyring" but it is locked". Set to blank password:
```mv ~/.local/share/keyrings/Default_Keyring.keyring old_Default_Keyring.keyring```
```reboot and set to blank password. Ignore the warning```


**Install and configure dnsmasq for WiFi AP DNS and DHCP
------------------------------
dnsmasq provides DHCP addresses to devices connecting to the Pi's WiFi access
point, and resolves the hostname 'enchantee' to the Pi so clients can use
friendly URLs like http://enchantee/display instead of an IP address.
All other DNS queries (internet hostnames) are forwarded to upstream servers.

Assumptions:
- hostapd is already configured and running on wlan0
- wlan0 has static IP 192.168.4.1 (set in /etc/dhcpcd.conf or equivalent):
  ```
  interface wlan0
      static ip_address=192.168.4.1/24
      nohook wpa_supplicant
  ```

Stop systemd-resolved to free port 53 (dnsmasq will take over DNS):
```sudo systemctl disable systemd-resolved```
```sudo systemctl stop systemd-resolved```
```sudo rm /etc/resolv.conf```
```echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf```

Install dnsmasq:
```sudo apt install dnsmasq```

Stop dnsmasq while configuring:
```sudo systemctl stop dnsmasq```

Copy the config from the provisioning repo:
```sudo cp provisioning/enchantee/etc/dnsmasq.d/enchantee.conf /etc/dnsmasq.d/enchantee.conf```

Enable and start dnsmasq:
```sudo systemctl enable dnsmasq```
```sudo systemctl start dnsmasq```

Verify dnsmasq is running and resolving enchantee:
```sudo systemctl status dnsmasq```
```nslookup enchantee 127.0.0.1```


**Install and configure nginx as reverse proxy
------------------------------
nginx routes requests for http://enchantee/* to the correct docker service:
  http://enchantee/display  → Node-Red dashboard UI  (container port 1880)
  http://enchantee/grafana/ → Grafana                (container port 3000)
  http://enchantee/upload   → File upload endpoint   (container port 1880)

nginx only binds to the WiFi AP interface (192.168.4.1:80) so internet-facing
interfaces are not affected. All non-enchantee traffic bypasses nginx entirely
and routes normally through the Pi's internet connection.

Install nginx:
```sudo apt install nginx```

Copy the enchantee site config:
```sudo cp provisioning/enchantee/etc/nginx/sites-available/enchantee /etc/nginx/sites-available/enchantee```

Enable the enchantee site and disable the default site:
```sudo ln -s /etc/nginx/sites-available/enchantee /etc/nginx/sites-enabled/enchantee```
```sudo rm /etc/nginx/sites-enabled/default```

Update .env - set GRAFANA_URL to use the enchantee hostname and subpath.
Grafana is configured with GF_SERVER_SERVE_FROM_SUB_PATH=true in docker-compose.yml
so it can serve correctly from the /grafana/ subpath:
```GRAFANA_URL=http://enchantee/grafana```
```DOMAIN_NAME=enchantee```

After updating .env, restart the grafana container to apply the new root URL:
```docker compose up -d grafana```

Configure the Node-Red file upload flow at /upload:
In the Node-Red editor (http://enchantee:1880), create an HTTP-in node
listening on POST /upload, connected to your file handling logic. The nginx
config at /upload proxies to Node-Red port 1880. Adjust the proxy_pass port
in /etc/nginx/sites-available/enchantee if using a different service.

Test the nginx configuration:
```sudo nginx -t```

Start nginx:
```sudo systemctl enable nginx```
```sudo systemctl start nginx```

Verify the services are reachable from a device connected to the WiFi AP:
```curl http://enchantee/display```
```curl http://enchantee/grafana/```
