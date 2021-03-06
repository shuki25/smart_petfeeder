# Generated by Django 4.0.4 on 2022-05-31 21:59

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0012_alter_devicestatus_firmware_version'),
    ]

    operations = [
        migrations.CreateModel(
            name='NotificationAlertTracking',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('offline_alert', models.BooleanField(default=False)),
                ('low_hopper_alert', models.BooleanField(default=False)),
                ('power_disconnect_alert', models.BooleanField(default=False)),
                ('low_battery_alert', models.BooleanField(default=False)),
                ('device_owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='app.deviceowner')),
            ],
        ),
    ]
