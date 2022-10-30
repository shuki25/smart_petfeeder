from django.urls import include, path
from rest_framework import routers

from api import views

router = routers.DefaultRouter()
# router.register(r"users", views.UserViewSet)
# router.register(r"groups", views.GroupViewSet)
router.register(r"pets", views.PetViewSet)
router.register(r"feeding-schedule", views.FeedingScheduleViewSet)
router.register(r"settings", views.SettingsViewSet)
router.register(r"feeding-log", views.FeedingLogViewSet)
router.register(r"recent-feeding", views.RecentFeedingViewSet)
router.register(r"device/settings", views.DeviceOwnerViewSet)
# router.register(r"devices", views.DeviceViewSet)
router.register(r"devices/own", views.DevicesOwnedViewSet)

# Wire up our API using automatic URL routing.
# Additionally, we include login URLs for the browsable API.

urlpatterns = [
    path("", include(router.urls)),
    path("next-meal/device/", views.get_next_meal),
    path("next-meal/", views.get_all_next_meal),
    path("device/verify/<device_id>/<secret_key>/", views.verify_device),
    path("device/heartbeat/", views.heartbeat),
    path("event/task-completed/", views.event_task_completed),
    path("account/local/auth/<username>/", views.authenticate_account),
    path("account/local/create/", views.create_local_account),
    path("account/local/exists/<username>/", views.local_account_exists),
    path("account/local/exists/<username>/<email>/", views.local_account_exists),
    path("account/google/exists/<uid>/", views.google_account_exists),
    path("account/google/auth/<uid>/", views.google_account),
    path("account/google/create/", views.create_google_account),
    path("account/settings/", views.account_settings),
    path("device/activate/", views.activate_device),
    path("menu/<menu_id>/", views.get_menu),
]
