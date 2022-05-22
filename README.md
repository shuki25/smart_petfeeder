# Petnet Rescued

*Petnet Rescued* is a web application that interacts with a now defunct cloud-based *Petnet.io* feeder (First generation only). With this web application and Raspberry Pi 3/4 server, it will allow *Petnet.io* owners to continue using their feeders again with hardware modifications to the device.

## Materials needed for build

You will need the following parts to modify your feeder.

1. Petnet.io feeder - First generation
2. 1 x Raspberry Pi 3B+/4
3. 1 x 4.3" Nextion Enhanced Display (NX4827K043) - [Amazon](https://www.amazon.com/gp/product/B07BL3D5DW/ref=ppx_yo_dt_b_asin_title_o03_s00)
4. 1 x RPi Power Relay Board Expansion Module for Raspberry Pi A+ B+ 2B 3B - [Amazon](https://www.amazon.com/gp/product/B07CZL2SKN/ref=ppx_yo_dt_b_asin_title_o01_s01)
5. 1 x 16 GB Micro SDHC UHS-1 Class 10 Memory Card - [Amazon](https://www.amazon.com/Sandisk-Ultra-Micro-UHS-I-Adapter/dp/B073K14CVB/ref=pd_bxgy_img_1/137-6913224-8596123)
5. 1 x Proto Strip Board for Raspberry Pi - [ThePiHut](https://thepihut.com/collections/raspberry-pi-hats/products/raspberry-pi-proto-strip-board)
6. 1 x GPIO Stacking Header for Pi A+/B+/Pi 2/Pi 3 (Extra-long 2x20 Pins) - [Amazon](https://www.amazon.com/Adafruit-Stacking-Header-Raspberry-Pi/dp/B013013XIQ/ref=sr_1_24) / [ThePiHut](https://thepihut.com/products/gpio-stacking-header-for-pi-a-b-pi-2-pi-3)
7. 

## Assembly

Hardware assembly instructions can be followed at [Instructables]().

## Raspberry Pi 3B+/4 Install

1. Download Raspberry Pi OS Lite from [www.raspberrypi.com](https://www.raspberrypi.com/software/operating-systems/).
2. Flash the image to Micro SD card and plug the card into RPi 3B+/4.
3. Mount the Micro SD card after flashing. Navigate to the boot directory and create an empty file called ssh. This will enable SSH server on boot for remote access.
4. Boot up the RPi.
5. Log in as pi with raspberry as password.
6. Do the following line command steps:
```bash
$ sudo raspi-config
```
7. Select System Options to configure your local Wireless settings and change the Hostname to `petnet-rescued`. Change the default pi password to something more secure.
8. Select Interface Options ->  Serial Port. Select **No** for login shell and **Yes** for serial port hardware to be enabled.
9. Select Localization Options to configure timezone and your keyboard settings.
10. Get your RPi local network address by executing `ifconfig` line command. Look for `wlan0` interface and identify the IP address. Write down the IP address.
```bash
$ ifconfig
```
11. Reboot the Rpi.
```bash
$ reboot
```
12. SSH into RPi with the IP address from step 9.
```bash
$ sudo apt update
$ sudo apt upgrade
$ sudo apt install python3 python3-pip python3-venv idle3 git nginx
$ sudo reboot
```
13. After rebooting, SSH back into RPi and do the following:
```bash
$ sudo adduser django dialout
$ sudo adduser django gpio
$ su - django
$ git clone https://github.com/shuki25/petnet_rescued.git
$ cd petnet_rescued/
$ python3 -m venv venv
$ source venv/bin/activate
$ pip install -r requirements.txt
$ ./manage.py migrate
$ ./manage.py createsuperuser
```
14. Add your IP address to `ALLOWED_HOSTS` in `petnet_rescued/settings.py` as shown below and save the changes before starting up the server. Replace the {RPi IP address} with your IP address.
```
ALLOWED_HOSTS = ["localhost", "{RPi IP address}"]
```

15. Modify the GPIO pinouts configurations in the `monitor.py` file based on your wiring setup. Choose one of the following pinouts configurations that matches your wiring:

If you are using a relay hat without the Raspberry Pi breadboard hat, use the following pinouts:
```python
# 5V Relay for motor 
RELAY_PIN = 20  # Relay 2

# PetNet Pin out for combined button/led module
RED_LED_PIN = 27  # Red wire
WHITE_LED_PIN = 17  # Orange wire
BUTTON_PIN = 22  # Brown wire 22

# Hopper Sensor
HOPPER_SENSOR_PIN = 25  # low = obstructed, high = not obstructed

# Photo Interrupter Encoder
OPTICAL_ENCODER_SIGNAL = 24
OPTICAL_ENCODER_POWER = 23
```
If you are using the Raspberry Pi breadboard hat, use the following pinouts:
```python
# 5V Relay for motor 
RELAY_PIN = 25  # Relay

# PetNet Pin out for combined button/led module
RED_LED_PIN = 22  # Red wire
WHITE_LED_PIN = 23  # Orange wire
BUTTON_PIN = 27  # Brown wire 22

# Hopper Sensor
HOPPER_SENSOR_PIN = 5  # low = obstructed, high = not obstructed

# Photo Interrupter Encoder
OPTICAL_ENCODER_SIGNAL = 19
OPTICAL_ENCODER_POWER = 0 # not used
```

16. Flash Nextion firmware to the Nextion Enchanced Display
```bash
$ nextion-fw-upload -b 9600 -ub 115200 /dev/ttyS0 nextion-display/petnet-rescued.tft
```
17. Install necessary configuration files:
```bash
$ sudo cp install/monitor.service /lib/systemd/system
$ sudo cp install/gunicorn.service /lib/systemd/system
$ sudo systemctl daemon-reload
$ sudo systemctl enable monitor.service
$ sudo systemctl enable gunicorn.service
$ sudo systemctl start gunicorn.service

$ sudo cp install/nginx-petnet-rescued /etc/nginx/sites-available/petnet-rescued
$ sudo ln -s /etc/nginx/sites-available/petnet-rescued /etc/nginx/sites-enabled
$ sudo rm /etc/nginx/sites-enabled/default
$ sudo systemctl restart nginx

$ sudo systemctl start monitor.service
```
18. Set up the configuration to allow the execution of rebooting task which requires superuser privileges
```bash
$ sudo echo "shutdown:x:28:django" >> /etc/group
$ sudo echo "%shutdown ALL=(ALL:ALL) NOPASSWD: /sbin/shutdown" >> /etc/sudoers
```
19. Reboot the system
```bash
$ reboot
```