import datetime
import hashlib
import json
import logging
from itertools import chain
from time import sleep

import pytz
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render

from .models import (
    AnimalSize,
    AnimalType,
    Article,
    Device,
    DeviceOwner,
    DeviceStatus,
    EventQueue,
    FeederModel,
    FeedingLog,
    FeedingSchedule,
    MotorTiming,
    NotificationSettings,
    Pet,
    PosixTimezone,
    Settings,
)
from .pushover import client
from .utils import (
    generate_device_key,
    get_next_feeding,
    seconds_to_days,
    update_has_event_tasks,
    update_setting,
    uptime,
    xss_token,
)

log = logging.getLogger(__name__)


# Create your views here.
def index(request):
    articles = Article.objects.filter(is_visible=True)
    data = {
        "title": "Smart PetFeeder Home Page",
        "articles": articles,
    }
    return render(request, "index.html", context=data)


@login_required
def dashboard(request):
    s = Settings.objects.filter(user_id=request.user.id).values()
    user_settings = {row["name"]: row["value"] for row in s}
    timezone = user_settings["timezone"] if "timezone" in user_settings else "UTC"
    devices = DeviceOwner.objects.filter(user_id=request.user.id).order_by("name")
    devices_owned = []

    for i in devices:
        devices_owned.append(i.device_id)

    device_info = []
    i = 0

    for device in devices:
        device_status = DeviceStatus.objects.get(device_id=device.device_id)

        online = True
        last_ping = uptime(device_status.last_ping)
        if last_ping > 500:
            online = False

        log.debug("Last ping: %d" % last_ping)
        next_meal = get_next_feeding(device.device_id, user_settings["timezone"])
        feedings = FeedingLog.objects.filter(device_owner__device_id=device.device_id).order_by("-feed_timestamp")[:5]

        if device_status.battery_crate > 0:
            crate_time = round(((100 - device_status.battery_soc) / device_status.battery_crate) * 3600)
        elif device_status.battery_crate != 0:
            crate_time = round((device_status.battery_soc / abs(device_status.battery_crate)) * 3600)
        else:
            crate_time = 0

        device_info.append(
            {
                "uptime": seconds_to_days(uptime(device_status.last_boot)),
                "next_meal": next_meal,
                "feedings": feedings,
                "device": device,
                "online": "Online" if online else "Offline",
                "device_status": device_status,
                "crate_time": str(datetime.timedelta(seconds=crate_time)),
            }
        )
        i += 1

    data = {
        "title": "Smart PetFeeder Home Page",
        "settings": user_settings,
        "timezone": timezone,
        "info": sorted(device_info, key=lambda z: (z["online"]), reverse=True),
        # "info": device_info,
        "num_feeders": len(device_info),
    }
    return render(request, "dashboard.html", context=data)


@login_required
def manual_feed(request, device_owner_id):

    try:
        device_owner = DeviceOwner.objects.get(id=device_owner_id)
    except ObjectDoesNotExist:
        messages.error(request, "Bad request. Manual feed cancelled.")
        return HttpResponseRedirect("/")

    device_id = device_owner.device_id

    if device_owner.user_id != request.user.id:
        messages.error(request, "Bad request. Manual feed cancelled.")
        return HttpResponseRedirect("/")

    try:
        motor_timing = MotorTiming.objects.get(feed_amount=0.25)
        ticks = motor_timing.interrupter_count
    except ObjectDoesNotExist:
        ticks = 7

    try:
        device_status = DeviceStatus.objects.get(device_id=device_id)
        device_status.has_event = True
        device_status.save()
    except ObjectDoesNotExist:
        messages.error(request, "Internal error. Manual feed cancelled.")
        return HttpResponseRedirect("/")

    payload = {"feed_amt": 0.25, "ticks": ticks}
    event = EventQueue(
        device_owner_id=device_owner_id,
        event_code=100,
        status_code="P",
        json_payload=payload,
    )
    if event is not None:
        event.save()
        messages.success(
            request,
            "Manual feed request sent to feeder. Please allow 5-10 seconds for the feeder to dispense the food.",
        )
        sleep(3)
    else:
        messages.error("Internal error. Manual feed cancelled")

    return HttpResponseRedirect("/")


@login_required
def view_schedule(request):
    s = Settings.objects.filter(user_id=request.user.id).values()
    user_settings = {row["name"]: row["value"] for row in s}
    timezone = user_settings["timezone"] if "timezone" in user_settings else "UTC"

    active_schedule = FeedingSchedule.objects.filter(
        device__deviceowner__user_id=request.user.id, active_flag=True
    ).order_by("local_time")
    inactive_schedule = FeedingSchedule.objects.filter(
        device__deviceowner__user_id=request.user.id, active_flag=False
    ).order_by("local_time")

    the_list = [active_schedule, inactive_schedule]
    list_title = ["Active Feeding Times", "Inactive Feeding Times"]

    data = {
        "title": "Feeding Schedule",
        "num_record": len(active_schedule) + len(inactive_schedule),
        "schedule": zip(list_title, the_list),
        "timezone": timezone,
    }
    return render(request, "schedule.html", context=data)


@login_required
def toggle_schedule(request, schedule_id):
    try:
        schedule = FeedingSchedule.objects.get(id=schedule_id, device__deviceowner__user_id=request.user.id)
        schedule.active_flag = not schedule.active_flag
        schedule.save()
        if schedule.active_flag:
            messages.success(request, "The feeding time is now active.")
        else:
            messages.success(request, "The feeding time is now inactive.")

    except ObjectDoesNotExist:
        messages.error(request, "Feeding time was not found.")

    return HttpResponseRedirect("/schedule/")


@login_required
def remove_schedule(request):
    if request.method == "POST":
        schedule_id = request.POST.get("id")
        token = request.POST.get("token")
        if token == xss_token("remove-feed-time", schedule_id):
            try:
                schedule = FeedingSchedule.objects.get(id=schedule_id, device__deviceowner__user_id=request.user.id)
                schedule.delete()
                messages.success(request, "Feeding time was successfully removed.")
            except ObjectDoesNotExist:
                messages.error(request, "Feeding time was not found.")
    return HttpResponseRedirect("/schedule/")


@login_required
def add_edit_schedule(request, schedule_id=None):
    s = Settings.objects.filter(user_id=request.user.id).values()
    user_settings = {row["name"]: row["value"] for row in s}
    timezone = user_settings["timezone"] if "timezone" in user_settings else "UTC"
    schedule = None
    error = False

    if schedule_id is None:
        schedule = FeedingSchedule()
        schedule.time = datetime.datetime.now().strftime("%H:00:00")
        schedule.dow = 127
    else:
        try:
            schedule = FeedingSchedule.objects.get(device__deviceowner__user_id=request.user.id, id=schedule_id)
        except ObjectDoesNotExist:
            messages.error(request, "Record not found.")
            return HttpResponseRedirect("/schedule/")

    if request.method == "POST":
        print(request.POST)
        schedule.meal_name = request.POST.get("meal_name", "Untitled")
        schedule.active_flag = request.POST.get("active_flag", False)
        dow_list = request.POST.getlist("dow")
        dow_list = [int(n) if n else 0 for n in dow_list]
        schedule.dow = sum(dow_list)
        try:
            if request.POST["device_owner_id"]:
                schedule.device_owner_id = request.POST["device_owner_id"]
                device_owner = DeviceOwner.objects.get(id=request.POST["device_owner_id"])
                schedule.device = device_owner.device
            else:
                raise KeyError
        except KeyError:
            messages.error(request, "Not saved. Please select a feeder.")
            error = True
        try:
            if request.POST["pet_id"]:
                schedule.pet_id = request.POST["pet_id"]
            else:
                raise KeyError
        except KeyError:
            messages.error(request, "Not saved. Please select a pet.")
            error = True
        try:
            if request.POST["motor_timing_id"]:
                schedule.motor_timing_id = request.POST["motor_timing_id"]
            else:
                raise KeyError
        except KeyError:
            messages.error(request, "Not saved. Please select a portion size.")
            error = True
        try:
            feeding_time = "%s:00" % request.POST["time"]
            schedule.local_time = "%s:00" % feeding_time
            current = datetime.datetime.now()
            local_datetime_str = "%04d-%02d-%02d %s" % (
                current.year,
                current.month,
                current.day,
                feeding_time,
            )
            local_tz = pytz.timezone(timezone)
            naive_datetime = datetime.datetime.strptime(local_datetime_str, "%Y-%m-%d %H:%M:%S")
            local_datetime = local_tz.localize(naive_datetime)
            utc_datetime = local_datetime.astimezone(pytz.utc)
            schedule.time = utc_datetime.strftime("%H:%M:%S")
        except KeyError:
            messages.error(request, "Not saved. Please enter feeding time.")
            error = True

        if not error:
            # try:
            schedule.save()
            # eq = EventQueue.objects.filter(
            #     device_owner_id=schedule.device_owner_id, event_code=300, status_code="P"
            # )
            # if not len(eq):
            #     event_queue = EventQueue(device_owner_id=schedule.device_owner_id, event_code=300, status_code="P")
            #     event_queue.save()
            if schedule_id is None:
                messages.success(request, "Feeding time added.")
            else:
                messages.success(request, "Feeding time saved.")
            return HttpResponseRedirect("/schedule/")
            # except Exception as e:
            #     messages.error(request, "Internal Error: %s" % e)

    device_owner = DeviceOwner.objects.filter(user_id=request.user.id)
    motor_timings = MotorTiming.objects.all().order_by("feed_amount")
    pets = Pet.objects.filter(user_id=request.user.id)

    data = {
        "title": "Editing a Feeding Time",
        "schedule": schedule,
        "device": device_owner,
        "timezone": timezone,
        "motor_timings": motor_timings,
        "pets": pets,
    }
    return render(request, "edit_schedule.html", context=data)


@login_required
def view_pets(request):
    s = Settings.objects.filter(user_id=request.user.id).values()
    user_settings = {row["name"]: row["value"] for row in s}
    timezone = user_settings["timezone"] if "timezone" in user_settings else "UTC"
    pet_data = Pet.objects.filter(user_id=request.user.id)

    pets = []

    for i, pet in enumerate(pet_data):
        schedule = FeedingSchedule.objects.filter(pet_id=pet.id).order_by("local_time")
        pets.append(
            {
                "info": pet,
                "schedule": schedule,
            }
        )

    context = {
        "title": "Pets",
        "pets": pets,
        "settings": user_settings,
        "timezone": timezone,
        "num_pets": len(pets),
    }

    return render(request, "pets.html", context=context)


@login_required
def add_edit_pet(request, pet_id=None):
    s = Settings.objects.filter(user_id=request.user.id).values()
    user_settings = {row["name"]: row["value"] for row in s}
    timezone = user_settings["timezone"] if "timezone" in user_settings else "UTC"
    animal_size = AnimalSize.objects.all()
    animal_type = AnimalType.objects.all()
    title = "Editing Pet Profile"
    error = False

    if pet_id is None:
        pet = Pet(user_id=request.user.id)
        title = "Adding a New Pet Profile"
    else:
        try:
            pet = Pet.objects.get(id=pet_id, user_id=request.user.id)
        except ObjectDoesNotExist:
            messages.error(request, "Pet not found in the database.")
            return HttpResponseRedirect("/pets/")

    if request.method == "POST":
        try:
            if request.POST["name"]:
                pet.name = request.POST.get("name")
            else:
                raise KeyError
        except KeyError:
            messages.error(request, "Please enter your pet's name")
            error = True

        try:
            if request.POST["animal_size_id"]:
                pet.animal_size_id = request.POST.get("animal_size_id")
            else:
                raise KeyError
        except KeyError:
            messages.error(request, "Please select your pet size")
            error = True

        try:
            if request.POST["animal_type_id"]:
                pet.animal_type_id = request.POST.get("animal_type_id")
            else:
                raise KeyError
        except KeyError:
            messages.error(request, "Please select your pet type")
            error = True

        try:
            if request.POST["weight"]:
                pet.weight = request.POST.get("weight")
            else:
                raise KeyError
        except KeyError:
            messages.error(request, "Please enter your pet's weight")
            error = True

        if not error:
            try:
                pet.save()
                if pet_id is None:
                    messages.success(request, "Pet profile added.")
                else:
                    messages.success(request, "Pet profile saved.")
                return HttpResponseRedirect("/pets/")
            except Exception as e:
                messages.error(request, "Internal Error: %s" % e)

    context = {
        "title": title,
        "pet": pet,
        "settings": user_settings,
        "timezone": timezone,
        "animal_size": animal_size,
        "animal_type": animal_type,
        "action": "edit",
    }

    return render(request, "edit_pet.html", context=context)


@login_required
def add_pet(request):
    s = Settings.objects.filter(user_id=request.user.id).values()
    animal_size = AnimalSize.objects.all()
    animal_type = AnimalType.objects.all()

    if request.method == "GET":
        context = {
            "title": "Adding a Pet Profile",
            "animal_size": animal_size,
            "animal_type": animal_type,
            "action": "new",
        }
        return render(request, "edit_pet.html", context=context)

    elif request.method == "POST":
        pet = Pet(user_id=request.user.id)
        pet.name = request.POST["name"]
        pet.animal_size_id = request.POST["animal_size_id"]
        pet.animal_type_id = request.POST["animal_type_id"]
        pet.weight = request.POST["weight"]
        pet.save()
        messages.success(request, "Pet profile added.")
        return HttpResponseRedirect("/pets/")

    else:
        messages.error(request, "Unknown error.")
        return HttpResponseRedirect("/pets/")


@login_required
def remove_pet(request):
    if request.method == "POST":
        pet_id = request.POST.get("id")
        token = request.POST.get("token")
        if token == xss_token("remove_pet", pet_id):
            try:
                pet = Pet.objects.get(id=pet_id, user_id=request.user.id)
                pet.delete()
                messages.success(request, "Pet profile successfully removed.")

            except ObjectDoesNotExist:
                messages.error("Pet profile not found.")
    return HttpResponseRedirect("/pets/")


@login_required
def feeders(request):
    s = Settings.objects.filter(user_id=request.user.id).values()
    user_settings = {row["name"]: row["value"] for row in s}
    timezone = user_settings["timezone"] if "timezone" in user_settings else "UTC"
    devices = DeviceOwner.objects.filter(user_id=request.user.id).order_by("name")
    devices_owned = []

    for i in devices:
        devices_owned.append(i.device_id)

    data = {}
    device_info = []
    i = 0

    for device in devices:
        device_status = DeviceStatus.objects.get(device_id=device.device_id)

        online = True
        last_ping = uptime(device_status.last_ping)
        if last_ping > 500:
            online = False

        log.debug("Last ping: %d" % last_ping)
        next_meal = get_next_feeding(device.device_id, user_settings["timezone"])
        feedings = FeedingLog.objects.filter(device_owner__device_id=device.device_id).order_by("-feed_timestamp")[:5]
        if device_status.battery_crate > 0:
            crate_time = round(((100 - device_status.battery_soc) / device_status.battery_crate) * 3600)
        elif device_status.battery_crate != 0:
            crate_time = round((device_status.battery_soc / abs(device_status.battery_crate)) * 3600)
        else:
            crate_time = 0

        device_info.append(
            {
                "uptime": seconds_to_days(uptime(device_status.last_boot)),
                "device": device,
                "online": "Online" if online else "Offline",
                "device_status": device_status,
                "crate_time": str(datetime.timedelta(seconds=crate_time)),
            }
        )
        i += 1

    data = {
        "title": "Registered Feeders",
        "settings": user_settings,
        "timezone": timezone,
        "info": sorted(device_info, key=lambda z: z["online"], reverse=True),
        "num_feeders": len(device_info),
    }
    return render(request, "feeders.html", context=data)


@login_required
def edit_feeder(request, device_owner_id):
    feeder_models = FeederModel.objects.all().order_by("brand_name", "model_name")
    motor_timings = MotorTiming.objects.all().order_by("feed_amount")

    try:
        device_owner = DeviceOwner.objects.get(id=device_owner_id, user_id=request.user.id)
    except ObjectDoesNotExist:
        messages.error(request, "Device is not found in the database.")
        return HttpResponseRedirect("/feeders/")

    if request.method == "POST":
        mt = FeederModel.objects.filter(image_path=request.POST["feeder_model_image_path"])
        feeder_model_id = mt[0].id if len(mt) else None
        device_owner.name = request.POST["name"]
        device_owner.feeder_model_id = feeder_model_id
        device_owner.manual_motor_timing_id = request.POST["manual_motor_timing_id"]
        device_owner.manual_button = True if "manual_button" in request.POST else False
        device_owner.save()
        messages.success(request, "Settings have been saved.")
        return HttpResponseRedirect("/feeders/")

    data = {
        "title": "Editing Feeder Details",
        "device": device_owner,
        "feeder_models": feeder_models,
        "motor_timings": motor_timings,
    }
    return render(request, "edit_feeder.html", context=data)


@login_required
def activate_feeder(request):
    feeder_models = FeederModel.objects.all().order_by("brand_name", "model_name")
    motor_timings = MotorTiming.objects.all().order_by("feed_amount")

    data = {
        "title": "Adding Feeder Details",
        "feeder_models": feeder_models,
        "motor_timings": motor_timings,
    }

    form_fields = ["device_id", "activation_code", ""]

    if request.method == "GET":
        if "device_id" in request.GET:
            data["device_id"] = request.GET["device_id"]

        if "device_key" in request.GET:
            data["device_key"] = request.GET["device_key"]

    if request.method == "POST":
        error = False

        mt = FeederModel.objects.filter(image_path=request.POST["feeder_model_image_path"])
        feeder_model_id = mt[0].id if len(mt) else None

        if feeder_model_id is None:
            error = True
            messages.error(request, "Please select the feeder model.")

        manual_motor_timing_id = None

        try:
            if request.POST["manual_motor_timing_id"]:
                manual_motor_timing_id = request.POST["manual_motor_timing_id"]
            else:
                error = True
                raise KeyError
        except KeyError:
            messages.error(request, "Please select portion size.")

        device = DeviceOwner(
            user_id=request.user.id,
            name=request.POST.get("name", "Untitled Feeder"),
            feeder_model_id=feeder_model_id,
            manual_motor_timing_id=manual_motor_timing_id,
            manual_button=True if "manual_button" in request.POST else False,
        )
        data["device"] = device
        data["device_id"] = request.POST["device_id"]

        try:
            d = Device.objects.get(
                control_board_identifier=request.POST["device_id"], secret_key=request.POST["activation_code"]
            )
            status = is_device_registered(request.POST["device_id"], request.user.id)
            if status["already_registered"]:
                messages.error(request, "Device is already registered. Please check and try again.")
            else:
                if not error:
                    device.device = d
                    device.save()
                    device.device_key = generate_device_key(device.id)
                    device.save()
                    messages.success(
                        request, "The control board is now registered and your feeder has been added to your account."
                    )
                    return HttpResponseRedirect("/feeders/")

        except ObjectDoesNotExist:
            messages.error(request, "Invalid activation code. Please check and try again.")

    return render(request, "edit_feeder.html", context=data)


@login_required
def remove_feeder(request):
    if request.method == "POST":
        device_owner_id = request.POST.get("id")
        token = request.POST.get("token")
        if token == xss_token("remove_feeder", device_owner_id):
            try:
                device_owner_id = DeviceOwner.objects.get(id=device_owner_id, user_id=request.user.id)
                device_owner_id.delete()
                messages.success(request, "Feeder successfully removed.")

            except ObjectDoesNotExist:
                messages.error("Feeder is not found.")
    return HttpResponseRedirect("/feeders/")


@login_required
def settings(request):
    if request.user.id:
        try:
            notification_settings = NotificationSettings.objects.get(user_id=request.user.id)
        except ObjectDoesNotExist:
            notification_settings = NotificationSettings(user_id=request.user.id, pushover_user_key="")
    else:
        notification_settings = None

    if request.method == "POST":
        settings_list = ["timezone, tz_esp32"]
        try:
            ptz = PosixTimezone.objects.get(id=request.POST["posix_timezone_id"])
            update_setting("timezone", ptz.timezone, request.user.id)
            update_setting("tz_esp32", ptz.posix_tz, request.user.id)
            devices = DeviceOwner.objects.filter(user_id=request.user.id)
            # for device in devices:
            #     event_queue = EventQueue(device_owner_id=device.id, event_code=400, status_code="P")
            #     event_queue.save()
            #     update_has_event_tasks(device.device_id)
            if len(devices):
                messages.success(request, "Settings Saved. Changes are being synced with feeders.")
            else:
                messages.success(request, "Settings Saved.")
        except ObjectDoesNotExist:
            messages.error(request, "Object not found. Settings not saved.")

        if "notification_options" in request.POST:
            options = request.POST.getlist("notification_options")
            notification_settings.auto_food = True if "auto_food" in options else False
            notification_settings.manual_food = True if "manual_food" in options else False
            notification_settings.feeder_offline = True if "feeder_offline" in options else False
            notification_settings.low_hopper = True if "low_hopper" in options else False
            notification_settings.power_disconnected = True if "power_disconnected" in options else False
            notification_settings.low_battery = True if "low_battery" in options else False
        else:
            notification_settings.auto_food = False
            notification_settings.manual_food = False
            notification_settings.feeder_offline = False
            notification_settings.low_hopper = False
            notification_settings.power_disconnected = False
            notification_settings.low_battery = False

        notification_settings.pushover_user_key = request.POST["user_key"]
        notification_settings.pushover_devices = request.POST["device_list"]
        notification_settings.save()

    s = Settings.objects.filter(user_id=request.user.id).values()
    user_settings = {row["name"]: row["value"] for row in s}
    timezones = PosixTimezone.objects.all()

    context = {
        "title": "Settings",
        "settings": user_settings,
        "timezones": timezones,
        "notification_settings": notification_settings,
    }

    return render(request, "settings.html", context=context)


@login_required
def pushover_verify(request, user_key):

    if user_key is None:
        raise ValueError("user_key is required.")

    c = client.Pushover()
    r = c.validate_user(user_key)

    return HttpResponse(r.text, content_type="application/json")


def is_device_registered(device_id, user_id):
    device = Device.objects.filter(control_board_identifier=device_id)
    device_owner = DeviceOwner.objects.filter(device__control_board_identifier=device_id)
    already_owned = False
    if len(device_owner):
        already_owned = device_owner[0].user_id == user_id
    data = {
        "status": len(device_owner) == 0 and len(device) > 0,
        "already_registered": len(device_owner) > 0,
        "already_owned": already_owned,
    }
    return data


@login_required
def validate_device_id(request, device_id):

    if device_id is None:
        raise ValueError("device_id is required.")

    data = is_device_registered(device_id, request.user.id)

    return JsonResponse(data)


@login_required
def setup(request):
    return render(request, "placeholder.html", context={"title": "Setup"})


@login_required
def help_page(request):
    return render(request, "placeholder.html", context={"title": "Help"})
