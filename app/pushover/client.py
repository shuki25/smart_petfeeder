import time

import requests
from django.conf import settings


class Pushover:
    def __init__(self, api_key=None, base_url=None):
        if settings.PUSHOVER_API_KEY:
            self.api_key = api_key if api_key else settings.PUSHOVER_API_KEY
        else:
            raise ValueError("PUSHOVER_API_KEY is not set")

        self.base_url = base_url if base_url else "https://api.pushover.net"
        self.last_sent = 0
        self.session = requests.session()

    def send_message(self, user_key, device, title, message, priority):
        url = "%s/1/messages.json" % self.base_url

        if user_key and device:
            post_content = {
                "token": self.api_key,
                "user": user_key,
                "device": device,
                "title": title if title else "Untitled",
                "message": message,
                "priority": priority,
            }
        else:
            raise ValueError("user_key and device are required.")

        current_time = int(time.time())

        if self.last_sent != 0 and current_time < self.last_sent:
            wait_time = 2 - (current_time - self.last_sent)
            print("Friendly API protocol: waiting %d seconds\n" % wait_time)
            time.sleep(wait_time)

        r = self.session.request("POST", url, data=post_content)
        self.last_sent = int(time.time())

        return r

    def validate_user(self, user_key):
        url = "%s/1/users/validate.json" % self.base_url

        if user_key:
            post_content = {
                "token": self.api_key,
                "user": user_key,
            }
        else:
            raise ValueError("user_key is required.")

        current_time = int(time.time())

        if self.last_sent != 0 and current_time < self.last_sent:
            wait_time = 2 - (current_time - self.last_sent)
            print("Friendly API protocol: waiting %d seconds\n" % wait_time)
            time.sleep(wait_time)

        r = self.session.request("POST", url, data=post_content)
        self.last_sent = int(time.time())

        return r
