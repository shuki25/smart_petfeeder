import datetime
import hashlib
import json
import logging
import os
import uuid
from itertools import chain
from time import sleep

import pytz
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.template.defaultfilters import filesizeformat
from django.utils import timezone
from PIL import Image

from app.tasks import send_pushover_notification

from .forms import PetForm
from .models import (
    AnimalSize,
    AnimalType,
    Article,
    Carousel,
    Device,
    DeviceOwner,
    DeviceStatus,
    EventQueue,
    FirmwareUpdate,
    FeederModel,
    FeedingLog,
    FeedingSchedule,
    MessageQueue,
    MotorTiming,
    NotificationSettings,
    Pet,
    PosixTimezone,
    Settings,
)
from .pushover.client import Pushover
from .utils import (
    battery_time,
    generate_device_key,
    get_next_feeding,
    is_device_registered,
    resize_and_crop,
    seconds_to_days,
    update_has_event_tasks,
    update_setting,
    uptime,
    xss_token,
)

log = logging.getLogger(__name__)
media_root = settings.MEDIA_ROOT


# Create your views here.
def index(request):
    articles = Article.objects.filter(is_visible=True)
    carousels = Carousel.objects.filter(
        is_visible=True,
        is_active=True,
        start_datetime__lte=timezone.now(),
        end_datetime__gte=timezone.now(),
    ).order_by("start_datetime")
    data = {
        "title": "Smart PetFeeder Home Page",
        "articles": articles,
        "carousels": carousels,
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

        crate_time = battery_time(device_status.battery_soc, device_status.battery_crate)

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
        motor_timing = MotorTiming.objects.get(id=device_owner.manual_motor_timing_id)
        ticks = motor_timing.interrupter_count
        feed_amt = motor_timing.feed_amount
    except ObjectDoesNotExist:
        feed_amt = 0.25
        ticks = 7

    try:
        device_status = DeviceStatus.objects.get(device_id=device_id)
        device_status.has_event = True
        device_status.save()
    except ObjectDoesNotExist:
        messages.error(request, "Internal error. Manual feed cancelled.")
        return HttpResponseRedirect("/")

    payload = {"feed_amt": feed_amt, "ticks": ticks}
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
    else:
        messages.error("Internal error. Manual feed cancelled")

    return HttpResponseRedirect("/dashboard/")


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
                messages.success(request, "Feeding time was successfully removed.")
                try:
                    eq = EventQueue.objects.filter(
                        device_owner_id=schedule.device_owner_id, event_code=300, status_code="P"
                    )
                    if not len(eq):
                        event_queue = EventQueue(
                            device_owner_id=schedule.device_owner_id, event_code=300, status_code="P"
                        )
                        event_queue.save()
                        update_has_event_tasks(schedule.device_id)
                except Exception as e:
                    messages.error(request, "Internal Error. Error creating event queue: %s" % e)
                schedule.delete()
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
    previous_device_owner = None

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
            if request.POST["previous_device_owner_id"] != "":
                previous_device_owner = DeviceOwner.objects.get(id=request.POST["previous_device_owner_id"])
        except KeyError:
            previous_device_owner = None
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
            schedule.local_time = feeding_time
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
            if previous_device_owner is not None:
                try:
                    eq = EventQueue.objects.filter(
                        device_owner_id=previous_device_owner.id, event_code=300, status_code="P"
                    )
                    if not len(eq):
                        event_queue = EventQueue(
                            device_owner_id=previous_device_owner.id, event_code=300, status_code="P"
                        )
                        event_queue.save()
                        update_has_event_tasks(previous_device_owner.device_id)
                except Exception as e:
                    messages.error(request, "Internal Error. Error creating event queue: %s" % e)
            schedule.save()

            if schedule_id is None:
                messages.success(request, "Feeding time added.")
            else:
                messages.success(request, "Feeding time saved.")
            return HttpResponseRedirect("/schedule/")

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
def upload_pet_photo(request):
    media_base = media_root
    data = {"is_valid": False, "message": "Bad method"}
    if request.method == "POST":
        form = PetForm(request.POST, request.FILES)
        if form.is_valid():
            pet_id = request.POST.get("id", None)
            if pet_id == "None":
                pet_id = None
            try:
                if pet_id is not None:
                    pet = Pet.objects.get(id=pet_id, user_id=request.user.id)
                    if pet.photo:
                        os.remove(media_base + str(pet.photo))
                else:
                    raise ObjectDoesNotExist
            except ObjectDoesNotExist:
                pet = Pet(user_id=request.user.id)
            pet.photo = request.FILES["photo"]
            pet.save()
            img_path = media_base + str(pet.photo)
            log.info("img_path: %s" % img_path)
            # modified_photo = str(pet.photo).split(".")[:-1][0] + "-thumb.png"
            modified_photo = "pet_photos/" + str(uuid.uuid4()) + ".png"
            img_modified_path = media_base + modified_photo
            log.info("modified_path: %s" % img_modified_path)
            i = 20
            while i > 0:
                if os.path.isfile(img_path) is False:
                    i -= 1
                    if i == 0:
                        data = {"is_valid": False, "message": "Upload failed"}
                        return JsonResponse(data)
                    sleep(0.5)
                else:
                    break
            resize_and_crop(img_path, img_modified_path, (213, 316), crop_type="middle")
            pet.photo = modified_photo
            os.remove(img_path)
            pet.save()

            data = {
                "is_valid": True,
                "message": "Pet photo was successfully uploaded.",
                "pet_id": pet.id,
                "path": str(pet.photo),
            }
    return JsonResponse(data)


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
        pet_id = request.POST.get("pet_id")
        if pet_id != "None" and pet_id is not None:
            pet = Pet.objects.get(id=pet_id, user_id=request.user.id)
        else:
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
        try:
            device_status = DeviceStatus.objects.get(device_id=device.device_id)

            online = True
            last_ping = uptime(device_status.last_ping)
            if last_ping > 500:
                online = False

            log.debug("Last ping: %d" % last_ping)
            next_meal = get_next_feeding(device.device_id, user_settings["timezone"])
            feedings = FeedingLog.objects.filter(device_owner__device_id=device.device_id).order_by("-feed_timestamp")[
                :5
            ]

            crate_time = battery_time(device_status.battery_soc, device_status.battery_crate)

            firmware_update = (
                FirmwareUpdate.objects.filter(control_board__revision=device_status.control_board_revision)
                .order_by("-created_at")
                .first()
            )

            device_info.append(
                {
                    "uptime": seconds_to_days(uptime(device_status.last_boot)),
                    "device": device,
                    "online": "Online" if online else "Offline",
                    "device_status": device_status,
                    "crate_time": str(datetime.timedelta(seconds=crate_time)),
                    "firmware_update": firmware_update,
                }
            )
            i += 1
        except ObjectDoesNotExist:
            log.error("Unable to get DeviceStatus")

    data = {
        "title": "Registered Feeders",
        "settings": user_settings,
        "timezone": timezone,
        "info": sorted(device_info, key=lambda z: z["online"], reverse=True),
        "num_feeders": len(device_info),
        "upgrade_active": request.GET.get("upgrade_active", False),
    }
    return render(request, "feeders.html", context=data)


@login_required
def edit_feeder(request, device_owner_id):
    feeder_models = FeederModel.objects.all().order_by("brand_name", "model_name")
    motor_timings = MotorTiming.objects.all().order_by("feed_amount")

    try:
        device_owner = DeviceOwner.objects.get(id=device_owner_id, user_id=request.user.id)
        device_status = DeviceStatus.objects.get(device_id=device_owner.device_id)
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
        device_status.hopper_level = request.POST.get("hopper_level", 0)
        device_status.save(update_fields=["hopper_level"])
        device_owner.save()
        messages.success(request, "Settings have been saved.")
        return HttpResponseRedirect("/feeders/")

    data = {
        "title": "Editing Feeder Details",
        "device": device_owner,
        "feeder_models": feeder_models,
        "motor_timings": motor_timings,
        "device_status": device_status,
        "hopper_amount": "%.1f" % ((device_owner.feeder_model.hopper_capacity * device_status.hopper_level) / 100),
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
                device_owner = DeviceOwner.objects.get(id=device_owner_id, user_id=request.user.id)
                device_owner.delete()
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
            rs = Settings.objects.filter(user_id=request.user.id, name="timezone").first()
            old_settings = None
            if rs:
                old_settings = rs.value

            if old_settings != ptz.timezone:
                log.info("Timezone changed, updating feeding times to %s timezone", ptz.timezone)
                update_setting("timezone", ptz.timezone, request.user.id)
                update_setting("tz_esp32", ptz.posix_tz, request.user.id)
                devices = DeviceOwner.objects.filter(user_id=request.user.id)

                scheduled_feedings = FeedingSchedule.objects.filter(device_owner__user_id=request.user.id)
                for schedule in scheduled_feedings:
                    log.info("processing feeding schedule id: %d", schedule.id)
                    feeding_time = schedule.local_time
                    current = datetime.datetime.now()
                    local_datetime_str = "%04d-%02d-%02d %s" % (
                        current.year,
                        current.month,
                        current.day,
                        feeding_time,
                    )
                    local_tz = pytz.timezone(ptz.timezone)
                    naive_datetime = datetime.datetime.strptime(local_datetime_str, "%Y-%m-%d %H:%M:%S")
                    local_datetime = local_tz.localize(naive_datetime)
                    utc_datetime = local_datetime.astimezone(pytz.utc)
                    schedule.time = utc_datetime.strftime("%H:%M:%S")
                    schedule.save()

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

        if notification_settings.pushover_user_key == "" and request.POST["user_key"] != "":
            MessageQueue(
                user_id=request.user.id,
                title="Pushover Notification Enabled",
                message="You are receiving this notification because you provided the user key to the notification settings. The Pushover Notification is now enabled.",
            ).save()
        elif notification_settings.pushover_user_key != "" and request.POST["user_key"] == "":
            MessageQueue(
                user_id=request.user.id,
                title="Pushover Notification Disabled",
                message="You are receiving this notification because you removed the user key to the notification settings. The Pushover Notification is now disabled.",
            ).save()
            send_pushover_notification.apply_async(args=[request.user.id])
            sleep(2)
        elif (
            notification_settings.pushover_user_key != request.POST["user_key"]
            and notification_settings.pushover_user_key != ""
            and request.POST["user_key"] != ""
        ):
            MessageQueue(
                user_id=request.user.id,
                title="Pushover Notification Settings Update",
                message="You are receiving this notification because you changed the user key to the notification settings. The record has been updated to use the new user key.",
            ).save()

        notification_settings.pushover_user_key = request.POST["user_key"]
        notification_settings.pushover_devices = request.POST["device_list"]
        notification_settings.save()

        send_pushover_notification.apply_async(args=[request.user.id])

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

    c = Pushover()
    r = c.validate_user(user_key)

    return HttpResponse(r.text, content_type="application/json")


@login_required
def validate_device_id(request, device_id):

    if device_id is None:
        raise ValueError("device_id is required.")

    data = is_device_registered(device_id, request.user.id)

    return JsonResponse(data)


@login_required
def setup(request):
    if request.method == "POST":
        is_setup_done = request.POST.get("is_setup_done", 0)
        log.info("is setup finished? is_setup_done: %s", is_setup_done)
        rs, is_created = Settings.objects.get_or_create(user_id=request.user.id, name="is_setup_done")
        rs.value = int(is_setup_done)
        rs.save()
        messages.success(request, "Initial account setup is complete.")
        return HttpResponseRedirect("/dashboard/")

    return render(request, "setup.html", context={"title": "Setup"})


@login_required
def upgrade_firmware(request):
    if request.method == "POST":
        device_owner_id = request.POST.get("device_owner_id", None)
        if device_owner_id:
            try:
                device = DeviceOwner.objects.get(user_id=request.user.id, id=device_owner_id)
                event = EventQueue(event_code=800, device_owner_id=device.id)
                event.save()
                status, is_created = DeviceStatus.objects.get_or_create(device_id=device.device_id)
                status.has_event = True
                status.save()
                messages.success(
                    request,
                    "Firmware Upgrade in progress. Please allow few minutes for the upgrade to complete. Do not turn off the feeder during the upgrade.",
                )
            except ObjectDoesNotExist:
                messages.error(request, "Unknown device. Upgrade cancelled.")
                return HttpResponseRedirect("/feeders/")
        else:
            messages.error(request, "Unknown device. Upgrade cancelled.")
        return HttpResponseRedirect("/feeders/?upgrade_active=1")


@login_required
def help_page(request):
    return render(request, "placeholder.html", context={"title": "Help"})


@login_required
def feeder_calibration(request):
    return render(request, "placeholder.html", context={"title": "Calibrating Your Feeder"})
