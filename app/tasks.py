import datetime
import time

from celery.utils.log import get_logger
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from smart_petfeeder.celery import app

from .models import (
    DeviceOwner,
    DeviceStatus,
    MessageQueue,
    NotificationAlertTracking,
    NotificationSettings,
)
from .pushover.client import Pushover

log = get_logger(__name__)


@app.task(name="app.tasks.send_pushover_notification", soft_time_limit=300)
def send_pushover_notification(user_id):
    try:
        settings = NotificationSettings.objects.get(user_id=user_id)
    except ObjectDoesNotExist as e:
        log.exception("Exception raised: %r", e)
        return

    messages = MessageQueue.objects.filter(user_id=user_id, status_code="P").order_by(
        "created_at"
    )

    pushover = Pushover()

    for message in messages:
        r = pushover.send_message(
            settings.pushover_user_key,
            settings.pushover_devices,
            message.title,
            message.message,
            0,
        )
        if r.status_code != 200:
            log.warning(
                "Error returned from Pushover: %s - %s", r.status_code, r.reason
            )
            message.status_code = "E"
        else:
            message.status_code = "C"
        message.save()
        time.sleep(0.5)

    log.info("Sending pushover notification for user_id: %s", user_id)


@app.task(name="app.tasks.check_pushover_message_queue", soft_time_limit=300)
def check_pushover_message_queue():
    pushover = Pushover()

    messages = MessageQueue.objects.filter(status_code="P").order_by("created_at")[:5]

    for message in messages:
        try:
            user = NotificationSettings.objects.get(user_id=message.user_id)
            if user.pushover_user_key != "" and user.pushover_devices != "":
                log.info("Sending pushover notification for user_id: %s", user.user_id)
                r = pushover.send_message(
                    user.pushover_user_key,
                    user.pushover_devices,
                    message.title,
                    message.message,
                    0,
                )
                if r.status_code != 200:
                    log.warning(
                        "Error returned from Pushover: %s - %s", r.status_code, r.reason
                    )
                    message.status_code = "E"
                else:
                    message.status_code = "C"
            else:
                log.info(
                    "Notification for user_id %s not sent. Pushover was not configured."
                    % user.user_id
                )
                message.status_code = "E"
            message.save()
            time.sleep(0.5)
        except Exception as e:
            log.warning("Exception error: %r", e)


@app.task(name="app.tasks.check_offline_status", soft_time_limit=300)
def check_offline_status():
    devices = DeviceStatus.objects.filter(
        last_ping__lt=timezone.now() - datetime.timedelta(minutes=5)
    )
    for device in devices:
        try:
            device_owner = DeviceOwner.objects.get(device_id=device.device_id)
            notification_settings = NotificationSettings.objects.get(
                user_id=device_owner.user_id
            )
            alert_tracking = NotificationAlertTracking.objects.get(
                device_owner_id=device_owner.id
            )
            if (
                notification_settings.feeder_offline
                and not alert_tracking.offline_alert
                and notification_settings.pushover_user_key != ""
            ):
                MessageQueue(
                    device_owner_id=device_owner.id,
                    user_id=device_owner.user_id,
                    title=device_owner.name,
                    message="Your feeder is currently offline, possibly lost an internet connection or it was powered off.",
                ).save()
                alert_tracking.offline_alert = True
                alert_tracking.save()
        except ObjectDoesNotExist as e:
            log.error("record not found: %s" % e)
    pass
