# Smart PetFeeder

*Smart PetFeeder* is a web application that interacts with a now defunct cloud-based *Petnet.io* feeder (First generation only). With this web application and Raspberry Pi 3/4 server, it will allow *Petnet.io* owners to continue using their feeders again with hardware modifications to the device.

## Materials needed for build

You will need the following parts to modify your feeder.

1. Smart PetFeeder Control Board
2. JST-XH through-hole header (one 10-pins, three 2-pins, two 3-pins)
3. (optional) 6-pins header for ESP32 programmer if installing firmware yourself

## Installing Control Board

Hardware install instructions can be followed at [Instructables]().

## Setting up Cloud-based Server
1. Install Ubuntu Server (22.x LTS)
2. SSH into the server.
```bash
$ sudo apt update
$ sudo apt upgrade
$ sudo apt install python3 python3-pip python3-venv git nginx redis
$ sudo reboot
```
3. After rebooting, SSH back into the server and do the following:
```bash
$ sudo adduser django
$ su - django
$ git clone https://github.com/shuki25/smart_petfeeder.git
$ cd smart_petfeeder/
$ python3 -m venv venv
$ source venv/bin/activate
$ pip install -r requirements.txt
$ ./manage.py migrate
$ ./manage.py createsuperuser
```
4. Add your IP address to `ALLOWED_HOSTS` in `smart_petfeeder/settings.py` as shown below and save the changes before starting up the server. Replace the {RPi IP address} with your IP address.
```
ALLOWED_HOSTS = ["localhost", "{server IP address}"]
```


5. Install necessary system configuration files:
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

## Notes
Starting up Celery Worker (for testing)
```bash
celery -A smart_petfeeder worker -l info
```
Starting up Celery Beat (for testing)
```bash
celery -A smart_petfeeder beat -l info
```