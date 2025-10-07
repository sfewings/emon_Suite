*Enchantee installation instructions
===============================

**Enable serial port for Moteino emon input
------------------------------
in /boot/firmware/config.txt add:
```enable_uart=1```
reassign Bluetooth to use mini-UART:
```dtoverlay=miniuart-bt```
Connect Moteino to Raspberry Pi UART:
Moteino TX -> Pi RX (GPIO15)
Moteino RX -> Pi TX (GPIO14)
Moteino GND -> Pi GND  
UART can be accessed using ttyAMA0


**To enable Waveshare LED display
------------------------------
'''dtoverlay=vc4-kms-v3d'''
'''dtoverlay=vc4-kms-dsi-waveshare-panel,8_0_inch'''
