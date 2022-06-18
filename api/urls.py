from django.urls import include, path
from rest_framework import routers

from api import views

router = routers.DefaultRouter()
router.register(r"users", views.UserViewSet)
router.register(r"groups", views.GroupViewSet)
router.register(r"pets", views.PetViewSet)
router.register(r"feeding-schedule", views.FeedingScheduleViewSet)
router.register(r"settings", views.SettingsViewSet)
router.register(r"feeding-log", views.FeedingLogViewSet)
router.register(r"device/settings", views.DeviceOwnerViewSet)
router.register(r"devices", views.DeviceViewSet)

# Wire up our API using automatic URL routing.
# Additionally, we include login URLs for the browsable API.

urlpatterns = [
    path("", include(router.urls)),
    path("next-meal/", views.get_next_meal),
    path("device/verify/<device_id>/<secret_key>/", views.verify_device),
    path("device/heartbeat/", views.heartbeat),
    path("event/task-completed/", views.event_task_completed),
]
