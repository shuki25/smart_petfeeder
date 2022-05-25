"""petnet_rescued URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
# from django.contrib.auth.views import login, logout
from django.urls import include, path

from .views import (
    activate_feeder,
    add_edit_pet,
    add_edit_schedule,
    add_pet,
    dashboard,
    edit_feeder,
    feeders,
    help_page,
    index,
    manual_feed,
    pushover_verify,
    remove_feeder,
    remove_pet,
    remove_schedule,
    settings,
    setup,
    toggle_schedule,
    upload_pet_photo,
    validate_device_id,
    view_pets,
    view_schedule,
)

urlpatterns = [
    path("", index, name="home"),
    path("dashboard/", dashboard, name="dashboard"),
    path("pets/", view_pets, name="pets"),
    path("pets/edit/<pet_id>/", add_edit_pet, name="edit-pet"),
    path("pets/add/", add_edit_pet, name="add-pet"),
    path("pets/remove/", remove_pet, name="remove-pet"),
    path("pets/upload/", upload_pet_photo, name="upload-pet-photo"),
    path("feeders/", feeders, name="feeders"),
    path("feeders/edit/<device_owner_id>/", edit_feeder, name="edit-feeder"),
    path("feeders/validate/<device_id>/", validate_device_id, name="validate-device"),
    path("feeders/activate/", activate_feeder, name="activate-feeder"),
    path("feeders/remove/", remove_feeder, name="remove-feeder"),
    path("schedule/", view_schedule, name="schedule"),
    path("schedule/edit/<schedule_id>/", add_edit_schedule, name="edit-feed-time"),
    path("schedule/add/", add_edit_schedule, name="add-feed-time"),
    path("schedule/remove/", remove_schedule, name="remove-feed-time"),
    path("schedule/toggle/<schedule_id>/", toggle_schedule, name="toggle-feed-time"),
    path("settings/", settings, name="settings"),
    path("pushover/verify/<user_key>/", pushover_verify, name="pushover_verify"),
    path("setup/", setup, name="setup"),
    path("help/", help_page, name="help"),
    path("manual-feed/<int:device_owner_id>/", manual_feed, name="manual-feed"),
]
