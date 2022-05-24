import logging
from pathlib import Path
from .models import Settings

import yaml

log = logging.getLogger(__name__)

MENU_PATH = "%s%s" % (Path(__file__).resolve().parent, "/menu.yaml")


def menu_context(request):
    context_data = dict()
    try:
        with open(MENU_PATH) as file:
            data = yaml.full_load(file)

        context_data = {
            "menu_list": data,
            "current_route": request.resolver_match.view_name,
        }
        # print(context_data)
    except Exception as e:
        log.debug(e)

    return context_data


def account_setup_status(request):
    is_setup_done = 0
    setup_phase = 0

    lookup_table = {
        "setup": 0,
        "settings": 1,
        "add-pet": 2,
        "edit-pet": 2,
        "pets": 2,
        "activate-feeder": 3,
        "edit-feeder": 3,
        "feeders": 3,
        "add-feed-time": 4,
        "schedule": 4,
        "edit-feed-time": 4,
    }

    if request.user.id:
        settings = Settings.objects.filter(user_id=request.user.id, name="is_setup_done").first()

        if settings is not None:
            is_setup_done = int(settings.value)

    if request.resolver_match.view_name in lookup_table:
        setup_phase = lookup_table[request.resolver_match.view_name]

    context_data = {
        "is_setup_done": is_setup_done,
        "setup_phase": setup_phase,
    }

    return context_data
