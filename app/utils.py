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
from PIL import Image

from smart_petfeeder.settings import DEBUG

from .models import Device, DeviceOwner, DeviceStatus, EventQueue, FeedingSchedule, Settings


def uptime(boot_time):
    return datetime.utcnow().timestamp() - boot_time.timestamp()


def weekday_sun_zero(isoweekday):
    return 0 if isoweekday == 7 else isoweekday


def get_next_feeding(device_id, the_timezone="UTC"):
    current_tz = pytz.timezone(the_timezone)
    dow = weekday_sun_zero(datetime.now().isoweekday())
    current_time = datetime.now().time()
    dow_bit = 2**dow
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
        dow_bit = 2**dow
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
            "device_id": device_id,
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
            "device_id": device_id,
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
            "timezone": the_timezone,
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


def get_settings(user_id=None):
    data = {}

    if user_id:
        qs = Settings.objects.filter(user_id=user_id)
        for row in qs:
            data[row.name] = row.value
    else:
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


def resize_and_crop(img_path, modified_path, size, crop_type="top"):
    """
    Resize and crop an image to fit the specified size.

    args:
    img_path: path for the image to resize.
    modified_path: path to store the modified image.
    size: `(width, height)` tuple.
    crop_type: can be 'top', 'middle' or 'bottom', depending on this
    value, the image will cropped getting the 'top/left', 'middle' or
    'bottom/right' of the image to fit the size.
    raises:
    Exception: if can not open the file in img_path of there is problems
    to save the image.
    ValueError: if an invalid `crop_type` is provided.
    """
    # If height is higher we resize vertically, if not we resize horizontally
    img = Image.open(img_path)
    # Get current and desired ratio for the images
    img_ratio = img.size[0] / float(img.size[1])
    ratio = size[0] / float(size[1])
    # The image is scaled/cropped vertically or horizontally depending on the ratio
    if ratio > img_ratio:
        img = img.resize((size[0], int(round(size[0] * img.size[1] / img.size[0]))), Image.ANTIALIAS)
        # Crop in the top, middle or bottom
        if crop_type == "top":
            box = (0, 0, img.size[0], size[1])
        elif crop_type == "middle":
            box = (0, int(round((img.size[1] - size[1]) / 2)), img.size[0], int(round((img.size[1] + size[1]) / 2)))
        elif crop_type == "bottom":
            box = (0, img.size[1] - size[1], img.size[0], img.size[1])
        else:
            raise ValueError("ERROR: invalid value for crop_type")
        img = img.crop(box)
    elif ratio < img_ratio:
        img = img.resize((int(round(size[1] * img.size[0] / img.size[1])), size[1]), Image.ANTIALIAS)
        # Crop in the top, middle or bottom
        if crop_type == "top":
            box = (0, 0, size[0], img.size[1])
        elif crop_type == "middle":
            box = (int(round((img.size[0] - size[0]) / 2)), 0, int(round((img.size[0] + size[0]) / 2)), img.size[1])
        elif crop_type == "bottom":
            box = (img.size[0] - size[0], 0, img.size[0], img.size[1])
        else:
            raise ValueError("ERROR: invalid value for crop_type")
        img = img.crop(box)
    else:
        img = img.resize((size[0], size[1]), Image.ANTIALIAS)
    # If the scale is the same, we do not need to crop
    img.save(modified_path)


def battery_time(battery_soc, battery_crate):
    if battery_crate > 0:
        crate_time = round(((100 - battery_soc) / battery_crate) * 3600)
    elif battery_crate != 0:
        crate_time = round((battery_soc / abs(battery_crate)) * 3600)
    else:
        crate_time = 0

    return crate_time


def is_device_registered(device_id, user_id):
    device = Device.objects.filter(control_board_identifier=device_id)
    device_owner = DeviceOwner.objects.filter(device__control_board_identifier=device_id)
    already_owned = False
    if len(device_owner):
        already_owned = device_owner[0].user_id == user_id
    data = {
        "status": len(device_owner) == 0 and len(device) > 0,
        "can_register": len(device_owner) == 0 and len(device) > 0,
        "already_registered": len(device_owner) > 0,
        "already_owned": already_owned,
    }
    return data
