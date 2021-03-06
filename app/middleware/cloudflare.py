import logging

log = logging.getLogger(__name__)


class CloudflareMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            ip = request.headers["CF-Connecting-IP"]
        except KeyError:
            ip = request.META["REMOTE_ADDR"]
        request.ip = ip
        request.META["REMOTE_ADDR"] = ip
        return self.get_response(request)
