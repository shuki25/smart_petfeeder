import json
import logging
import re

from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import Group, User
from django.core import serializers
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from rest_framework import filters, permissions, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from app.models import (
    AnimalSize,
    AnimalType,
    Device,
    DeviceOwner,
    DeviceStatus,
    EventQueue,
    FeederModel,
    FeedingLog,
    FeedingSchedule,
    MessageQueue,
    MotorTiming,
    NotificationAlertTracking,
    NotificationSettings,
    Pet,
    PosixTimezone,
    Settings,
)
from app.utils import (
    battery_time,
    is_device_registered,
    generate_device_key,
    get_device_id,
    get_next_feeding,
    get_settings,
    update_has_event_tasks,
    update_ping,
    update_setting,
)

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


# User Agent Permission Check
class UserAgentPermission(permissions.BasePermission):
    """
    Check if user agent is valid
    """

    def has_permission(self, request, view):
        if "User-Agent" in request.headers:
            if request.headers["User-Agent"] in settings.ALLOWED_API_CLIENTS:
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
    permission_classes = [permissions.IsAuthenticated, UserAgentPermission]

    def get_queryset(self):
        try:
            return super().get_queryset().filter(user=self.request.user.id).order_by("name")

        except ObjectDoesNotExist:
            return None

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        serializer.save(user=self.request.user)

    def perform_destroy(self, instance):
        log.info("PetViewSet:perform_destroy")
        # instance.delete()
        pass


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
    API endpoint that allows settings to be viewed or edited.
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


class RecentFeedingViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows feeding log to be viewed or edited.
    """

    queryset = FeedingLog.objects.all()
    serializer_class = FeedingLogSerializer
    permission_classes = [permissions.IsAuthenticated, UserAgentPermission]
    filter_backends = (filters.SearchFilter,)

    search_fields = ["device_owner__id"]

    def get_queryset(self):
        try:
            device_list = []
            device_owner = DeviceOwner.objects.filter(user_id=self.request.user.id)
            for device in device_owner:
                device_list.append(device.id)
            return super().get_queryset().filter(device_owner_id__in=device_list).order_by("-feed_timestamp")

        except ObjectDoesNotExist:
            return None


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
    permission_classes = [permissions.IsAuthenticated, DevicePermission]
    lookup_field = "device__control_board_identifier"
    # pagination_class = None

    # def get_queryset(self):
    #     log.debug("We are inside Device Owner View Set")
    #     return super().get_queryset().filter(user_id=self.request.user.id)

    def get_queryset(self):
        try:
            device_owner = DeviceOwner.objects.get(
                user_id=self.request.user.id,
                device_key=self.request.headers["X-Device-Key"],
            )

            return super().get_queryset().filter(id=device_owner.id)

        except ObjectDoesNotExist:
            return None


class DevicesOwnedViewSet(viewsets.ModelViewSet):
    """
    API endpoint that lists associated device serial number to registered owner
    """

    queryset = DeviceOwner.objects.all().order_by("id")
    serializer_class = DeviceOwnerSerializer
    permission_classes = [permissions.IsAuthenticated, UserAgentPermission]
    lookup_field = "id"

    def get_queryset(self):
        return super().get_queryset().filter(user_id=self.request.user.id)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated, UserAgentPermission])
def activate_device(request):
    """
    API endpoint that allows device to be activated
    """

    data = {
        "status": "403",
        "message": "Device activation failed, invalid device id or activation code.",
    }

    if request.method == "POST":
        body_unicode = request.body.decode("utf-8")
        if body_unicode:
            try:
                form = json.loads(body_unicode)
            except ValueError:
                log.info("Invalid JSON")
                return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            log.info("Empty body")
            return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            device = Device.objects.get(control_board_identifier=form["device_id"], secret_key=form["activation_code"])
        except ObjectDoesNotExist:
            log.info("Device ID not found.")
            return Response(data, status=status.HTTP_403_FORBIDDEN)

        reg_status = is_device_registered(form["device_id"], request.user.id)
        del reg_status["status"]
        data["registration_status"] = reg_status
        if reg_status["already_registered"] and reg_status["already_owned"]:
            data["status"] = "400"
            data["message"] = "Device is already registered to you."
            return Response(data, status=status.HTTP_400_BAD_REQUEST)
        elif reg_status["already_registered"] and not reg_status["already_owned"]:
            data["status"] = "400"
            data["message"] = "Device is already registered to another user."
            return Response(data, status=status.HTTP_400_BAD_REQUEST)
        else:
            device_owned = DeviceOwner(
                user_id=request.user.id,
                device_id=device.id,
                manual_button=form["manual_button"],
                feeder_model_id=form["feeder_model_id"],
                name=form["name"],
                manual_motor_timing_id=form["manual_motor_timing_id"],
            )
            device_owned.save()
            device_owned.device_key = generate_device_key(device_owned.id)
            device_owned.save()
            data["status"] = "201"
            data["message"] = "Device activated successfully."
            return Response(data, status=status.HTTP_201_CREATED)
    else:
        log.info("Invalid request method")
        return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes((permissions.IsAuthenticated, DevicePermission))
def get_next_meal(request):
    """
    API endpoint that gives the next upcoming scheduled meal
    """
    user_settings = get_settings(user_id=request.user.id)

    if request.method == "GET":
        try:
            device_owner = DeviceOwner.objects.get(
                user_id=request.user.id,
                device_key=request.headers["X-Device-Key"],
            )
        except ObjectDoesNotExist:
            return Response({"error": "bad request"}, status=status.HTTP_404_NOT_FOUND)

        next_meal = get_next_feeding(device_owner.device_id, the_timezone=user_settings["timezone"])
        return Response(next_meal)
    else:
        return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes((permissions.IsAuthenticated,))
def get_all_next_meal(request):
    """
    API endpoint that gives the next upcoming scheduled meal for all devices owned by the user
    """
    user_settings = get_settings(user_id=request.user.id)
    next_meal = []

    if request.method == "GET":
        device_owner = DeviceOwner.objects.filter(user_id=request.user.id)
        for device in device_owner:
            next_meal.append(get_next_feeding(device.device_id, the_timezone=user_settings["timezone"]))
        return Response(next_meal)
    else:
        return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)


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
    device_info = Device.objects.filter(
        Q(control_board_identifier=kwargs["device_id"]) | Q(secret_key=kwargs["secret_key"])
    )
    device_valid = False
    device_exists = False

    for device in device_info:
        if device.control_board_identifier == kwargs["device_id"] and device.secret_key == kwargs["secret_key"]:
            device_valid = True
            break
        elif device.control_board_identifier == kwargs["device_id"]:
            device_exists = True

    if device_exists and not device_valid:
        data["status"] = 403
        return Response(data, status=status.HTTP_403_FORBIDDEN)

    if device_valid:
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
@permission_classes((permissions.AllowAny, UserAgentPermission))
def authenticate_account(request, *args, **kwargs):
    """
    API endpoint that checks for account status
    """

    data = {
        "status": 401,
        "message": "Invalid username or password",
        "api_key": None,
    }
    account_exist = False

    try:
        account_exist = User.objects.filter(username=kwargs["username"]).exists()
    except ObjectDoesNotExist:
        data["message"] = "Invalid username or password"

    if request.method == "POST":
        if account_exist:
            auth = authenticate(request=request, username=kwargs["username"], password=request.data["password"])
            if auth is not None:
                user = User.objects.get(username=kwargs["username"])
                data["status"] = 200
                data["message"] = "Valid account"
                data["api_key"] = Token.objects.get(user_id=auth.id).key
                data["user_id"] = user.id
                data["username"] = user.username
                data["email"] = user.email
                data["is_active"] = user.is_active
                data["last_login"] = user.last_login
                data["date_joined"] = user.date_joined
                return Response(data)
            else:
                data["message"] = "Invalid username or password"
                return Response(data, status=status.HTTP_401_UNAUTHORIZED)
    else:
        return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes((permissions.AllowAny, UserAgentPermission))
def google_account(request, *args, **kwargs):
    """
    API endpoint that checks for account status
    """

    data = {
        "status": 404,
        "message": "Not Found",
        "api_key": None,
    }

    account_exist = SocialAccount.objects.filter(uid=kwargs["uid"]).exists()

    if request.method == "GET":
        if account_exist:
            user = User.objects.get(socialaccount__uid=kwargs["uid"])
            data["status"] = 200
            data["message"] = "Valid account"
            data["api_key"] = Token.objects.get(user_id=user.id).key
            data["user_id"] = user.id
            data["username"] = user.username
            data["email"] = user.email
            data["is_active"] = user.is_active
            data["last_login"] = user.last_login
            data["date_joined"] = user.date_joined
        return Response(data)
    else:
        return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "POST"])
@permission_classes((permissions.IsAuthenticated,))
def account_settings(request, *args, **kwargs):
    """
    API endpoint that updates account settings
    """
    if request.method == "GET":
        data = {
            "status": 404,
            "message": "Not found",
            "settings": None,
        }
        settings_data = get_settings(user_id=request.user.id)

        if request.method == "GET" and len(settings_data) > 0:
            data["status"] = 200
            data["settings"] = settings_data
            data["message"] = "Settings found"
            return Response(data)
        else:
            return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == "POST":
        body_unicode = request.body.decode("utf-8")
        if body_unicode:
            try:
                body = json.loads(body_unicode)
            except ValueError:
                return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)

        data = {
            "status": 200,
            "message": "",
        }
        allowed_settings = ["is_setup_done", "timezone", "tz_esp32"]

        for key, value in body["settings"].items():
            if key in allowed_settings:
                if key == "timezone":
                    valid = PosixTimezone.objects.filter(timezone=value).exists()
                    if valid:
                        update_setting(key, value, user_id=request.user.id)
                        data["message"] += "Updated %s; " % key
                    else:
                        data["message"] += "Invalid timezone, not updated; "
                        data["status"] = 400
                elif key == "tz_esp32":
                    valid = PosixTimezone.objects.filter(posix_tz=value).exists()
                    if valid:
                        update_setting(key, value, user_id=request.user.id)
                        data["message"] += "Updated %s; " % key
                    else:
                        data["message"] += "Invalid tz_esp32, not updated; "
                        data["status"] = 400
                else:
                    try:
                        setting = Settings.objects.get(user_id=request.user.id, name=key)
                        setting.value = value
                        setting.save()
                    except ObjectDoesNotExist:
                        setting = Settings(user_id=request.user.id, name=key, value=value)
                        setting.save()
                    data["message"] += "Updated %s; " % key

        data["message"] = data["message"].strip()

        return Response(data)

    else:
        return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes((permissions.AllowAny, UserAgentPermission))
def local_account_exists(request, *args, **kwargs):
    """
    API endpoint that checks for account status
    """

    data = {
        "status": 404,
        "message": "Account not found",
    }

    try:
        if "email" in kwargs:
            user = User.objects.filter(Q(username=kwargs["username"]) | Q(email=kwargs["email"]))
        else:
            user = User.objects.filter(username=kwargs["username"])
        data["email"] = False
        data["username"] = False
        # data["user_id_list"] = [u["id"] for u in user.values("id")]
        for u in user:
            if u.username == kwargs["username"]:
                data["username"] = True
            if "email" in kwargs and u.email == kwargs["email"]:
                data["email"] = True

    except ObjectDoesNotExist:
        data["message"] = "Account not found"
        return Response(data, status=status.HTTP_404_NOT_FOUND)

    if not data["username"] and not data["email"]:
        return Response(data, status=status.HTTP_404_NOT_FOUND)
    elif data["username"] or data["email"]:
        data["status"] = 200
        data["message"] = "%d account(s) found" % len(user)
        return Response(data, status=status.HTTP_200_OK)
    else:
        return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes((permissions.AllowAny, UserAgentPermission))
def google_account_exists(request, *args, **kwargs):
    """
    API endpoint that checks for Google account status
    """

    data = {
        "status": 404,
        "message": "Google account not linked",
    }

    user = SocialAccount.objects.filter(uid=kwargs["uid"])
    if len(user) > 0:
        data["status"] = 200
        data["message"] = "Google account linked"
        return Response(data, status=status.HTTP_200_OK)
    else:
        return Response(data, status=status.HTTP_404_NOT_FOUND)


@api_view(["POST"])
@permission_classes((permissions.AllowAny, UserAgentPermission))
def create_local_account(request, *args, **kwargs):
    """
    API endpoint that creates a new local account
    """

    data = {
        "status": 400,
        "message": "Account not created",
    }

    if request.method == "POST":
        body_unicode = request.body.decode("utf-8")
        if body_unicode:
            try:
                form = json.loads(body_unicode)
            except ValueError:
                log.info("Invalid JSON")
                return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            log.info("Empty body")
            return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)

        if not User.objects.filter(username=form["username"]).exists():
            if not User.objects.filter(email=form["email"]).exists():
                user = User.objects.create_user(
                    username=form["username"],
                    email=form["email"],
                    password=request.data["password"],
                )
                user.save()
                data["status"] = 201
                data["message"] = "Account created"
            else:
                data["message"] = "Email already in use"
        else:
            data["message"] = "Username already in use"

        return Response(data, status=status.HTTP_201_CREATED)
    else:
        return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes((permissions.AllowAny, UserAgentPermission))
def create_google_account(request, *args, **kwargs):
    """
    API endpoint that creates a new Google account
    """

    data = {
        "status": 404,
        "message": "Account not created",
    }

    if request.method == "POST":
        if request.method == "POST":
            body_unicode = request.body.decode("utf-8")
            if body_unicode:
                form = json.loads(body_unicode)
            else:
                return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)

        if not User.objects.filter(username=form["username"]).exists():
            if not User.objects.filter(email=form["email"]).exists():
                user = User.objects.create_user(
                    username=form["username"],
                    email=form["email"],
                    password=form["google_id"],
                )
                user.save()
                data["status"] = 200
                data["message"] = "Account created"
            else:
                data["message"] = "Email already in use"
        else:
            data["message"] = "Username already in use"

        return Response(data)
    else:
        return Response({"error": "bad request"}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes((permissions.IsAuthenticated, UserAgentPermission))
def get_menu(request, *args, **kwargs):
    """
    API endpoint that returns the menu
    """
    if request.method == "GET" and "menu_id" in kwargs:
        rs = None
        menu_list = None
        if kwargs["menu_id"] == "portion_size":
            rs = MotorTiming.objects.all().order_by("feed_amount").values()
        elif kwargs["menu_id"] == "animal_size":
            rs = AnimalSize.objects.all().order_by("id").values()
        elif kwargs["menu_id"] == "animal_type":
            rs = AnimalType.objects.all().order_by("name").values()
        elif kwargs["menu_id"] == "feeder_model":
            rs = FeederModel.objects.all().order_by("model_name").values()
        elif kwargs["menu_id"] == "timezone":
            rs = PosixTimezone.objects.all().order_by("timezone").values()
        if rs:
            menu_list = [item for item in rs]
        if menu_list:
            data = {
                "status": 200,
                "message": "Menu found",
                "menu": menu_list,
            }
            return Response(data, status=status.HTTP_200_OK)
        else:
            return Response({"status": 404, "message": "Not Found"}, status=status.HTTP_404_NOT_FOUND)


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

        attr_list = [
            "battery_soc",
            "battery_voltage",
            "battery_crate",
            "on_power",
            "control_board_revision",
            "firmware_version",
            "is_hopper_low",
        ]
        device_status = DeviceStatus.objects.get(device_id=device_id)
        device_status.last_ping = timezone.now()
        for a in attr_list:
            if a in body:
                setattr(device_status, a, body[a])
        device_status.save()

        try:
            notification_settings = NotificationSettings.objects.get(user_id=request.user.id)
            alert_tracking = NotificationAlertTracking.objects.select_for_update().filter(
                device_owner__device_id=device_id
            )

            if notification_settings.feeder_offline:
                with transaction.atomic():
                    for alert in alert_tracking:
                        if alert.offline_alert:
                            alert.offline_alert = False
                            MessageQueue(
                                device_owner_id=alert.device_owner_id,
                                user_id=request.user.id,
                                title=alert.device_owner.name,
                                message="Your feeder is back online.",
                            ).save()
                            alert.save()

            if notification_settings.power_disconnected and not device_status.on_power:
                with transaction.atomic():
                    for alert in alert_tracking:
                        if not alert.power_disconnect_alert:
                            alert.power_disconnect_alert = True
                            MessageQueue(
                                device_owner_id=alert.device_owner_id,
                                user_id=request.user.id,
                                title=alert.device_owner.name,
                                message="Power has been disconnected from your feeder. It is currently running on battery.",
                            ).save()
                            alert.save()

            if notification_settings.power_disconnected and device_status.on_power:
                with transaction.atomic():
                    for alert in alert_tracking:
                        if alert.power_disconnect_alert:
                            alert.power_disconnect_alert = False
                            MessageQueue(
                                device_owner_id=alert.device_owner_id,
                                user_id=request.user.id,
                                title=alert.device_owner.name,
                                message="The power to your feeder has been restored.",
                            ).save()
                            alert.save()

            if notification_settings.low_battery and not device_status.on_power:
                with transaction.atomic():
                    for alert in alert_tracking:
                        crate_time = battery_time(device_status.battery_soc, device_status.battery_crate)

                        log.info("crate time: %s" % crate_time)
                        # If time remaining is less than 30 minutes, send notification.
                        if (
                            not alert.low_battery_alert
                            and 1800 > crate_time > 1500
                            and device_status.battery_crate < 0
                            and device_status.battery_voltage <= 3.30
                            and not device_status.on_power
                        ):
                            alert.low_battery_alert = True
                            MessageQueue(
                                device_owner_id=alert.device_owner_id,
                                user_id=request.user.id,
                                title=alert.device_owner.name,
                                message="Your feeder's backup battery has %d minutes of running time remaining. Please connect the power to the feeder as soon as possible."
                                % int(crate_time / 60),
                            ).save()
                            alert.save()

            if notification_settings.low_battery and device_status.on_power:
                with transaction.atomic():
                    for alert in alert_tracking:
                        if alert.low_battery_alert:
                            alert.low_battery_alert = False
                            alert.save()

            if notification_settings.low_hopper and device_status.is_hopper_low:
                with transaction.atomic():
                    for alert in alert_tracking:
                        if not alert.low_hopper_alert:
                            alert.low_hopper_alert = True
                            MessageQueue(
                                device_owner_id=alert.device_owner_id,
                                user_id=request.user.id,
                                title=alert.device_owner.name,
                                message="Your feeder is low on food. Please refill the hopper as soon as possible.",
                            ).save()
                            alert.save()

            if notification_settings.low_hopper and not device_status.is_hopper_low:
                with transaction.atomic():
                    for alert in alert_tracking:
                        if alert.low_hopper_alert:
                            alert.low_hopper_alert = False
                            MessageQueue(
                                device_owner_id=alert.device_owner_id,
                                user_id=request.user.id,
                                title=alert.device_owner.name,
                                message="The hopper has been filled up. Please indicate the current hopper level on the website.",
                            ).save()
                            alert.save()

        except ObjectDoesNotExist:
            log.error("user id %s not found", request.user.id)

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
