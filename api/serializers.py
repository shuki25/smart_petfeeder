from django.contrib.auth.models import Group, User
from rest_framework import serializers

from app.models import Device, DeviceOwner, FeedingLog, FeedingSchedule, Pet, Settings


class UserSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = User
        fields = ["url", "username", "email", "groups"]


class GroupSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Group
        fields = ["url", "name"]


class PetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pet
        fields = [
            "url",
            "name",
            "animal_type",
            "animal_size",
            "weight",
            "daily_calories_intake",
        ]
        depth = 1


class FeedingScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedingSchedule
        fields = ["id", "meal_name", "active_flag", "pet", "dow", "time", "motor_timing"]
        depth = 1


class SettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Settings
        fields = [
            "name",
            "value",
            "user_id",
        ]
        depth = 0


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = "__all__"
        depth = 0


class DeviceOwnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceOwner
        fields = [
            "id",
            "manual_button",
            "manual_motor_timing",
        ]
        depth = 1


class FeedingLogSerializer(serializers.ModelSerializer):
    device_owner = DeviceOwnerSerializer(read_only=True)

    class Meta:
        model = FeedingLog
        fields = [
            "id",
            "pet_name",
            "feed_type",
            "feed_amt",
            "feed_timestamp",
            "device_owner",
        ]
        depth = 0
