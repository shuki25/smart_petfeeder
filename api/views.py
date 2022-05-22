import json
import logging
import re

from django.contrib.auth.models import Group, User
from django.core import serializers
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError
from django.shortcuts import render
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from app.models import Device, DeviceOwner, DeviceStatus, EventQueue, FeedingLog, FeedingSchedule, Pet, Settings
from app.utils import get_device_id, get_next_feeding, get_settings, update_has_event_tasks, update_ping

from .serializers import (
    DeviceOwnerSerializer,
    DeviceSerializer,
    FeedingLogSerializer,
    FeedingScheduleSerializer,
    GroupSerializer,
    PetSerializer,
    SettingsSerializer,
    UserSerializer,
)

log = logging.getLogger(__name__)


# Device Permission Check
class DevicePermission(permissions.BasePermission):
    """
    Check if device key matches to an assigned user
    """

    def has_permission(self, request, view):
        if "X-Device-Key" in request.headers:
            owner = DeviceOwner.objects.filter(
                user_id=request.user.id,
                device_key=request.headers["X-Device-Key"],
            )
            if owner.exists():
                return True
            else:
                return False
        else:
            return False


# Create your views here.
class UserViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows users to be viewed or edited.
    """

    queryset = User.objects.all().order_by("-date_joined")
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]


class GroupViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """

    queryset = Group.objects.all()
    serializer_class = GroupSerializer
    permission_classes = [permissions.IsAuthenticated]


class PetViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allow pets to be viewed or edited.
    """

    queryset = Pet.objects.all().order_by("name")
    serializer_class = PetSerializer
    permission_classes = [permissions.IsAuthenticated]


class FeedingScheduleViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows feeding schedule to be viewed or edited.
    """

    queryset = FeedingSchedule.objects.all()
    serializer_class = FeedingScheduleSerializer
    permission_classes = [permissions.IsAuthenticated, DevicePermission]

    def get_queryset(self):
        try:
            device_owner = DeviceOwner.objects.get(
                user_id=self.request.user.id,
                device_key=self.request.headers["X-Device-Key"],
            )

            return (
                super().get_queryset().filter(device_owner_id=device_owner.id, active_flag=True).order_by("local_time")
            )

        except ObjectDoesNotExist:
            return None


class SettingsViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows feeding schedule to be viewed or edited.
    """

    queryset = Settings.objects.all().order_by("name")

    serializer_class = SettingsSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "name"

    def get_queryset(self):
        return super().get_queryset().filter(user_id=self.request.user.id)


class FeedingLogViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows feeding log to be viewed or edited.
    """

    queryset = FeedingLog.objects.all()
    serializer_class = FeedingLogSerializer
    permission_classes = [permissions.IsAuthenticated, DevicePermission]

    def get_queryset(self):
        try:
            device_owner = DeviceOwner.objects.get(
                user_id=self.request.user.id,
                device_key=self.request.headers["X-Device-Key"],
            )

            return super().get_queryset().filter(device_owner_id=device_owner.id)

        except ObjectDoesNotExist:
            return None

    def perform_create(self, serializer):
        try:
            device_owner = DeviceOwner.objects.get(
                user_id=self.request.user.id,
                device_key=self.request.headers["X-Device-Key"],
            )
        except ObjectDoesNotExist:
            log.info("Device ID not found.")
            raise IntegrityError
        log.info("Saving Log record")
        serializer.save(device_owner=device_owner)


@api_view(["GET"])
@permission_classes((permissions.IsAuthenticated,))
def get_next_meal(request):
    """
    API endpoint that gives the next upcoming scheduled meal
    """
    settings = get_settings()

    if request.method == "GET":
        next_meal = get_next_feeding(settings["timezone"])
        print(next_meal)
        return Response(next_meal)
    else:
        return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)


class DeviceViewSet(viewsets.ModelViewSet):
    """
    API endpoint that gives a list of device serial number
    """

    queryset = Device.objects.all().order_by("id")
    serializer_class = DeviceSerializer
    permission_classes = [permissions.IsAuthenticated]


class DeviceOwnerViewSet(viewsets.ModelViewSet):
    """
    API endpoint that lists associated device serial number to registered owner
    """

    queryset = DeviceOwner.objects.all().order_by("id")
    serializer_class = DeviceOwnerSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "device__control_board_identifier"

    def get_queryset(self):
        log.debug("We are inside Device Owner View Set")
        return super().get_queryset().filter(user_id=self.request.user.id)


@api_view(["GET"])
@permission_classes((permissions.AllowAny,))
def verify_device(request, *args, **kwargs):
    """
    API endpoint that gives the next upcoming scheduled meal
    """

    data = {
        "status": 404,
        # "device_id": kwargs["device_id"],
        # "secret_key": kwargs["secret_key"],
        "api_key": None,
    }
    device_info = Device.objects.filter(control_board_identifier=kwargs["device_id"], secret_key=kwargs["secret_key"])
    if len(device_info):
        try:
            owner = DeviceOwner.objects.get(device__control_board_identifier=kwargs["device_id"])
            log.debug("user_id: %d" % owner.user_id)
            api_key = Token.objects.get(user_id=owner.user_id)
            data["status"] = 200
            # data["device_info"] = serializers.serialize("json", device_info)
            data["api_key"] = api_key.key
            data["device_key"] = owner.device_key

            try:
                device_status = DeviceStatus.objects.get(device_id=owner.device_id)
                device_status.last_boot = timezone.now()
            except ObjectDoesNotExist:
                device_status = DeviceStatus(device_id=owner.device_id)

            device_status.save()

        except ObjectDoesNotExist:
            data["message"] = "Device not registered"
    else:
        if (
            len(kwargs["device_id"]) == 19
            and len(kwargs["secret_key"]) == 15
            and re.match(r"^ESP32-[0-9a-f]{4}-[0-9a-f]{8}$", kwargs["device_id"])
        ):
            log.debug("Passed device identifier string format")
            device = Device(
                control_board_identifier=kwargs["device_id"],
                secret_key=kwargs["secret_key"],
            )
            device.save()
            data["message"] = "Device ID %s added to database" % kwargs["device_id"]
        else:
            data["message"] = "Invalid device identifier"

    if request.method == "GET":
        return Response(data)
    else:
        return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes((permissions.IsAuthenticated, DevicePermission))
def heartbeat(request):
    """
    API endpoint that updates device status and check for any events to respond
    """

    if request.method == "POST":
        device_id = get_device_id(device_key=request.headers["X-Device-Key"], user_id=request.user.id)

        body_unicode = request.body.decode("utf-8")
        if body_unicode:
            body = json.loads(body_unicode)
        else:
            return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)

        device_status = DeviceStatus.objects.get(device_id=device_id)
        device_status.last_ping = timezone.now()
        device_status.battery_soc = body["battery_soc"]
        device_status.battery_voltage = body["battery_voltage"]
        device_status.battery_crate = body["battery_crate"]
        device_status.on_power = body["on_power"]
        device_status.save()

        data = {
            "status": 200,
            "has_event": device_status.has_event,
        }

        if device_status.has_event:
            event = (
                EventQueue.objects.filter(device_owner__device_id=device_id, status_code="P")
                .order_by("created_at")
                .values()
                .first()
            )
            if event is not None:
                data["event"] = event
            else:
                data["has_event"] = False

        return Response(data)
    else:
        return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes((permissions.IsAuthenticated, DevicePermission))
def event_task_completed(request):
    """
    API endpoint that updates an event task
    """

    if request.method == "POST":
        device_id = get_device_id(device_key=request.headers["X-Device-Key"], user_id=request.user.id)

        body_unicode = request.body.decode("utf-8")
        if body_unicode:
            body = json.loads(body_unicode)
        else:
            return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            event = EventQueue.objects.get(device_owner__device_id=device_id, id=body["id"])
            event.status_code = "C"
            event.save()
            update_ping(device_id)
            update_has_event_tasks(device_id)
            serialized_event = serializers.serialize("json", [event])
            data = {
                "status": 200,
                "event": json.loads(serialized_event)[0]["fields"],
            }
            return Response(data)

        except ObjectDoesNotExist:
            return Response({"error": "bad request"}, status=status.HTTP_404_NOT_FOUND)
