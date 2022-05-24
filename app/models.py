from datetime import date, datetime
from fractions import Fraction
import logging

import pytz
import qrcode
import qrcode.image.svg
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils.safestring import mark_safe
from django.utils.timezone import now
from rest_framework.authtoken.models import Token


log = logging.getLogger(__name__)


# Create your models here.
class AnimalType(models.Model):
    name = models.CharField(max_length=40)

    class Meta:
        db_table = "app_animal_type"


class AnimalSize(models.Model):
    name = models.CharField(max_length=20)

    class Meta:
        db_table = "app_animal_size"


class PosixTimezone(models.Model):
    timezone = models.CharField(max_length=50)
    posix_tz = models.CharField(max_length=50)

    class Meta:
        db_table = "app_posix_timezone"


class MotorTiming(models.Model):
    feed_amount = models.FloatField(default=0)
    motor_duration = models.IntegerField(default=0)
    interrupter_count = models.IntegerField(default=0)

    class Meta:
        db_table = "app_motor_timing"


class FeederModel(models.Model):
    brand_name = models.CharField(max_length=30)
    model_name = models.CharField(max_length=30)
    image_path = models.CharField(max_length=255)
    hopper_capacity = models.FloatField(default=20)
    has_hopper_sensor = models.BooleanField(default=True)
    has_motor_sensor = models.BooleanField(default=True)

    class Meta:
        db_table = "app_feeder_model"


class Device(models.Model):
    control_board_identifier = models.CharField(max_length=20)
    secret_key = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now=True)

    def activation_qrcode(self):
        url = "https://smartpetfeeder.net/feeders/activate/?device_id=%s&device_key=%s" % (
            self.control_board_identifier,
            self.secret_key,
        )
        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgImage)
        return mark_safe(img.to_string().decode())

    class Meta:
        db_table = "app_device"


class DeviceOwner(models.Model):
    device = models.ForeignKey(Device, models.CASCADE)
    user = models.ForeignKey(User, models.CASCADE)
    name = models.CharField(max_length=50, default="Unnamed Feeder")
    device_key = models.CharField(max_length=32, default="Key is not set")
    feeder_model = models.ForeignKey(FeederModel, models.CASCADE, null=True)
    manual_motor_timing = models.ForeignKey(MotorTiming, models.CASCADE, default=1)
    manual_button = models.BooleanField(default=True)

    class Meta:
        db_table = "app_device_owner"


class Pet(models.Model):
    user = models.ForeignKey(User, models.CASCADE)
    name = models.CharField(max_length=25)
    animal_type = models.ForeignKey(AnimalType, models.CASCADE, null=True)
    animal_size = models.ForeignKey(AnimalSize, models.CASCADE)
    weight = models.FloatField(default=0)
    daily_calories_intake = models.IntegerField(default=0)


class FeedingSchedule(models.Model):
    device = models.ForeignKey(Device, models.CASCADE)
    device_owner = models.ForeignKey(DeviceOwner, models.CASCADE)
    pet = models.ForeignKey(Pet, models.CASCADE)
    meal_name = models.CharField(max_length=20)
    active_flag = models.BooleanField(default=True)
    dow = models.SmallIntegerField(default=0)
    time = models.TimeField(default="06:00:00")
    local_time = models.TimeField(default="06:00:00")
    motor_timing = models.ForeignKey(MotorTiming, models.CASCADE, default=1)

    def utc_datetime(self):
        current = datetime.now()
        utc_datetime = "%04d-%02d-%02d %s" % (
            current.year,
            current.month,
            current.day,
            self.time,
        )
        return datetime.strptime(utc_datetime, "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.utc)

    class Meta:
        db_table = "app_feeding_schedule"


class FeedingLog(models.Model):
    class FeedType(models.TextChoices):
        MANUAL = "M", "Manual"
        AUTO = "S", "Scheduled"
        REMOTE = "R", "Remote"

    device_owner = models.ForeignKey(DeviceOwner, models.CASCADE)
    pet_name = models.CharField(max_length=80, default="Manual")
    feed_type = models.CharField(max_length=1, choices=FeedType.choices, default=FeedType.MANUAL)
    feed_amt = models.FloatField(default=0.5)
    feed_timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "app_feeding_log"

    def convert_timezone(self, timezone):
        dt = self.feed_timestamp
        return dt.astimezone(pytz.timezone(timezone))


class Settings(models.Model):
    user = models.ForeignKey(User, models.CASCADE)
    name = models.CharField(max_length=50)
    value = models.CharField(max_length=255)

    class Meta:
        db_table = "app_settings"


class EventQueue(models.Model):
    class StatusCode(models.TextChoices):
        PENDING = "P", "Pending"
        COMPLETED = "C", "Completed"

    device_owner = models.ForeignKey(DeviceOwner, models.CASCADE)
    event_code = models.IntegerField(null=True)
    json_payload = models.JSONField(max_length=1024, null=True)
    status_code = models.CharField(max_length=1, choices=StatusCode.choices, default=StatusCode.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "app_event_queue"


class DeviceStatus(models.Model):
    device = models.ForeignKey(Device, models.CASCADE)
    last_boot = models.DateTimeField(auto_now_add=True)
    last_ping = models.DateTimeField(auto_now_add=True)
    battery_voltage = models.FloatField(null=True, default=0.0)
    battery_soc = models.FloatField(null=True, default=0.0)
    battery_crate = models.FloatField(null=True, default=0.0)
    hopper_level = models.FloatField(null=True, default=0.0)
    has_event = models.BooleanField(default=False)
    on_power = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "app_device_status"


class MessageQueue(models.Model):
    class StatusCode(models.TextChoices):
        PENDING = "P", "Pending"
        COMPLETED = "C", "Completed"
        ERROR = "E", "Error"

    device_owner = models.ForeignKey(DeviceOwner, models.CASCADE, null=True)
    user = models.ForeignKey(User, models.CASCADE)
    status_code = models.CharField(max_length=1, choices=StatusCode.choices, default=StatusCode.PENDING)
    title = models.CharField(max_length=255, null=True)
    message = models.CharField(max_length=255, null=True)
    priority = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class NotificationSettings(models.Model):
    user = models.ForeignKey(User, models.CASCADE)
    pushover_user_key = models.CharField(max_length=32, default=None)
    pushover_devices = models.JSONField(max_length=2048, default=None)
    auto_food = models.BooleanField(default=False)
    manual_food = models.BooleanField(default=False)
    feeder_offline = models.BooleanField(default=False)
    low_hopper = models.BooleanField(default=False)
    power_disconnected = models.BooleanField(default=False)
    low_battery = models.BooleanField(default=False)


class ArticleCategory(models.Model):
    name = models.CharField(max_length=32, default=None)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Article categories"


class Article(models.Model):
    category = models.ForeignKey(ArticleCategory, models.CASCADE)
    title = models.CharField(max_length=256, default="Untitled Article Title")
    display_title = models.CharField(max_length=128, blank=True, null=True)
    author = models.CharField(max_length=64, default="Anonymous")
    content = models.TextField(default="Need content")
    is_pinned = models.BooleanField(default=False)
    is_visible = models.BooleanField(default=False)
    published_at = models.DateTimeField(editable=True, default=now)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_pinned", "-published_at"]


class Carousel(models.Model):
    name = models.CharField(max_length=50)
    img_src = models.CharField(max_length=255)
    slide_label = models.CharField(max_length=128)
    caption = models.CharField(max_length=128, blank=True, null=True)
    is_active = models.BooleanField(default=False)
    is_visible = models.BooleanField(default=False)
    start_datetime = models.DateTimeField(null=True)
    end_datetime = models.DateTimeField(null=True)


# Automatically add event to event queue by triggering post_save signal
# Automatically generate auth token by catching user's post_save signal
@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_auth_token(sender, instance=None, created=False, **kwargs):
    if created:
        Token.objects.create(user=instance)
        Settings.objects.create(user=instance, name="is_setup_done", value="0")


@receiver(post_save, sender=FeedingSchedule)
def add_event_queue_feeding_schedule_save(sender, instance=None, created=False, **kwargs):
    # eq = EventQueue.objects.filter(device_owner_id=instance.device_owner_id, event_code=300, status_code="P")
    # if not len(eq):
    log.info("in add_event_queue_feeding_schedule_save")
    EventQueue.objects.get_or_create(device_owner_id=instance.device_owner_id, event_code=300, status_code="P")
    status, is_created = DeviceStatus.objects.get_or_create(device_id=instance.device_id)
    status.has_event = True
    status.save()


@receiver(post_delete, sender=FeedingSchedule)
def add_event_queue_feeding_schedule_delete(sender, instance=None, created=False, **kwargs):
    # eq = EventQueue.objects.filter(device_owner_id=instance.device_owner_id, event_code=300, status_code="P")
    # if not len(eq):
    log.info("in add_event_queue_feeding_schedule_delete")
    EventQueue.objects.get_or_create(device_owner_id=instance.device_owner_id, event_code=300, status_code="P")
    status, is_created = DeviceStatus.objects.get_or_create(device_id=instance.device_id)
    status.has_event = True
    status.save()


@receiver(post_save, sender=Settings)
def add_event_queue2(sender, instance=None, created=False, **kwargs):
    devices = DeviceOwner.objects.filter(user_id=instance.user_id)
    for device in devices:
        EventQueue.objects.get_or_create(device_owner_id=device.id, event_code=400, status_code="P")
        status, is_created = DeviceStatus.objects.get_or_create(device_id=device.device_id)
        status.has_event = True
        status.save()


@receiver(post_save, sender=DeviceOwner)
def add_event_queue3(sender, instance=None, created=False, **kwargs):
    EventQueue.objects.get_or_create(device_owner_id=instance.id, event_code=400, status_code="P")
    status, is_created = DeviceStatus.objects.get_or_create(device_id=instance.device_id)
    status.has_event = True
    status.save()


@receiver(post_save, sender=FeedingLog)
def add_event_queue4(sender, instance=None, created=False, **kwargs):
    try:
        device = DeviceOwner.objects.get(id=instance.device_owner_id)
        user_settings = NotificationSettings.objects.filter(user_id=device.user_id).first()
        if user_settings.pushover_user_key != "":
            if instance.feed_type == "R" and user_settings.manual_food:
                message = "%s cup was manually dispensed from a remote computer or mobile device." % (
                    Fraction(instance.feed_amt)
                )
            elif instance.feed_type == "M" and user_settings.manual_food:
                message = "%s cup was manually dispensed from the feeder." % (Fraction(instance.feed_amt))
            elif user_settings.auto_food:
                message = "%s cup was automatically dispensed for %s." % (
                    Fraction(instance.feed_amt),
                    instance.pet_name,
                )
            MessageQueue(
                device_owner_id=instance.device_owner_id, user_id=device.user_id, title=device.name, message=message
            ).save()
    except ObjectDoesNotExist as e:
        log.warning("Object not found: %r", e)
