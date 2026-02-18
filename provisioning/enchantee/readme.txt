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
