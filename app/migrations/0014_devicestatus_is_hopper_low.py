# Generated by Django 4.0.4 on 2022-06-01 18:25

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0013_notificationalerttracking'),
    ]

    operations = [
        migrations.AddField(
            model_name='devicestatus',
            name='is_hopper_low',
            field=models.BooleanField(default=False),
        ),
    ]
