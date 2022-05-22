import logging
from pathlib import Path

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
