import time

from celery.utils.log import get_logger
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist

from .models import MessageQueue, NotificationSettings
from .pushover.client import Pushover
from smart_petfeeder.celery import app

log = get_logger(__name__)


@app.task(name="app.tasks.send_pushover_notification", soft_time_limit=300)
def send_pushover_notification(user_id):
    try:
        settings = NotificationSettings.objects.get(user_id=user_id)
    except ObjectDoesNotExist as e:
        log.exception("Exception raised: %r", e)
        return

    messages = MessageQueue.objects.filter(user_id=user_id, status_code="P").order_by("created_at")

    pushover = Pushover()

    for message in messages:
        r = pushover.send_message(
            settings.pushover_user_key, settings.pushover_devices, message.title, message.message, 0
        )
        if r.status_code != 200:
            log.warning("Error returned from Pushover: %s - %s", r.status_code, r.reason)
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
            log.info("Sending pushover notification for user_id: %s", user.user_id)
            r = pushover.send_message(user.pushover_user_key, user.pushover_devices, message.title, message.message, 0)
            if r.status_code != 200:
                log.warning("Error returned from Pushover: %s - %s", r.status_code, r.reason)
                message.status_code = "E"
            else:
                message.status_code = "C"
            message.save()
            time.sleep(0.5)
        except Exception as e:
            log.warning("Exception error: %r", e)
