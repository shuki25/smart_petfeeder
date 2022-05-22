import hashlib
import json
import time
from datetime import date, datetime
from fractions import Fraction

import psutil
import pytz
from django.conf import settings
from django.core import serializers
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import F
from django.utils import timezone

from smart_petfeeder.settings import DEBUG

from .models import DeviceOwner, DeviceStatus, EventQueue, FeedingSchedule, Settings


def uptime(boot_time):
    return datetime.utcnow().timestamp() - boot_time.timestamp()


def weekday_sun_zero(isoweekday):
    return 0 if isoweekday == 7 else isoweekday


def get_next_feeding(device_id, the_timezone="UTC"):
    current_tz = pytz.timezone(the_timezone)
    dow = weekday_sun_zero(datetime.now().isoweekday())
    current_time = datetime.now().time()
    dow_bit = 2 ** dow
    day = "today"
    rs = (
        FeedingSchedule.objects.annotate(dow_filter=F("dow").bitand(dow_bit))
        .filter(
            dow_filter__gt=0,
            time__range=[current_time, "23:59:59"],
            active_flag=1,
            device_id=device_id,
        )
        .order_by("time")
        .first()
    )
    if rs is None:
        dow = 0 if dow == 6 else dow + 1
        dow_bit = 2 ** dow
        rs = (
            FeedingSchedule.objects.annotate(dow_filter=F("dow").bitand(dow_bit))
            .filter(
                dow_filter__gt=0,
                active_flag=1,
                device_id=device_id,
            )
            .order_by("time")
            .first()
        )
        day = "tomorrow"

    if rs:
        data = {
            "has_meal": 1,
            "meal_id": rs.id,
            "meal_name": rs.meal_name,
            "pet_name": rs.pet.name,
            "size": str(Fraction(rs.motor_timing.feed_amount)),
            "duration": rs.motor_timing.motor_duration,
            "interrupter_count": rs.motor_timing.interrupter_count,
            "feed_time": rs.time,
            "feed_time_utc": str(rs.time),
            "feed_time_tz": str(convert_time_to_timezone(rs.time, the_timezone)),
            "day": day,
        }
    else:
        data = {
            "has_meal": 0,
            "meal_id": 0,
            "meal_name": "No scheduled meal",
            "pet_name": "",
            "size": "today or tomorrow",
            "duration": "",
            "interrupter_count": "",
            "feed_time": "",
            "feed_time_utc": "",
            "feed_time_tz": "",
            "day": "",
        }

    if DEBUG:
        data["debug"] = {
            "current_time": current_time,
            "timezone": timezone,
        }

    return data


def convert_time_to_timezone(utctime, the_timezone):
    dt = datetime.combine(date.today(), utctime, tzinfo=pytz.UTC)
    return dt.astimezone(pytz.timezone(the_timezone)).time()


def seconds_to_days(time):
    day = time // (24 * 3600)
    time = time % (24 * 3600)
    hour = time // 3600
    time %= 3600
    minutes = time // 60
    time %= 60
    seconds = time
    return "%d days, %02d:%02d:%02d" % (day, hour, minutes, seconds)


def get_settings():
    data = {}

    qs = Settings.objects.all()
    for row in qs:
        data[row.name] = row.value

    return data


def update_ping(device_id):
    try:
        device_status = DeviceStatus.objects.get(device_id=device_id)
        device_status.last_ping = timezone.now()
    except ObjectDoesNotExist:
        device_status = DeviceStatus(device_id=device_id)

    device_status.save()


def update_has_event_tasks(device_id):
    event = EventQueue.objects.filter(device_owner__device_id=device_id, status_code="P")
    try:
        status = DeviceStatus.objects.get(device_id=device_id)
        if event.exists():
            status.has_event = True
        else:
            status.has_event = False
        status.save()

    except ObjectDoesNotExist:
        pass


def get_device_id(device_key=None, user_id=None):
    if device_key and user_id:
        devices = DeviceOwner.objects.filter(user_id=user_id, device_key=device_key).order_by("device_id")
        if devices.exists():
            return devices[0].device_id
    return None


def update_setting(key, value, user_id=None):
    if user_id:
        try:
            setting = Settings.objects.get(user_id=user_id, name=key)
        except ObjectDoesNotExist:
            setting = Settings(user_id=user_id, name=key)
        setting.value = value
        setting.save()
        return True
    else:
        return False


def xss_token(action, key):
    s = "%s%s-%d" % (settings.SECRET_KEY, action, int(key))
    encoded_str = s.encode()
    return hashlib.sha1(encoded_str).hexdigest()


def generate_device_key(device_id):
    s = "%s-%d" % (settings.SECRET_KEY, int(device_id))
    encoded_str = s.encode()
    return hashlib.md5(encoded_str).hexdigest()
