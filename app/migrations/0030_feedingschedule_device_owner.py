# Generated by Django 3.2.9 on 2022-05-18 21:56

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0029_auto_20220518_1925'),
    ]

    operations = [
        migrations.AddField(
            model_name='feedingschedule',
            name='device_owner',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.CASCADE, to='app.deviceowner'),
            preserve_default=False,
        ),
    ]
