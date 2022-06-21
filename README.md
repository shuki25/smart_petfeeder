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
$ mkdir media/pet_photos
$ chmod -R 0775 media/pet_photos
$ chgrp -R www-data media/pet_photos
$ python3 -m venv venv
$ source venv/bin/activate
$ pip install -r requirements.txt
$ ./manage.py migrate
$ ./manage.py createsuperuser
$ ./manage.py loaddata fixtures/initial_data.json
$ ./manage.py loaddata fixtures/posix_timezone.json
$ ./manage.py collectstatic
```
4. Add your IP address to `ALLOWED_HOSTS` in `smart_petfeeder/settings.py` as shown below and save the changes before starting up the server. Replace the {RPi IP address} with your IP address.
```
ALLOWED_HOSTS = ["localhost", "{server IP address}"]
```


5. Install necessary system configuration files:
```bash
cp default/celery /etc/default 
cp install/etc/systemd/system/celery.service /lib/systemd/system
cp install/etc/systemd/system/celerybeat.service /lib/systemd/system
cp install/etc/systemd/system/gunicorn.service /lib/systemd/system
cp install/etc/tmpfiles.d/celery.conf /etc/tmpfiles.d
mkdir -p /var/log/celery
chown django:django /var/log/celery
mkdir -p /var/run/celery
chown django:django /var/run/celery
systemctl daemon-reload
systemctl enable celery.service
systemctl enable celerybeat.service
systemctl enable gunicorn.service
systemctl start gunicorn.service
systemctl start celery.service
systemctl start celerybeat.service

cp install/etc/nginx/sites-available/nginx-petnet-rescued /etc/nginx/sites-available/petnet-rescued
ln -s /etc/nginx/sites-available/petnet-rescued /etc/nginx/sites-enabled
rm /etc/nginx/sites-enabled/default
systemctl restart nginx
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