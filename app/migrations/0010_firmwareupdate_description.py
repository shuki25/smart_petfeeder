# Generated by Django 4.0.4 on 2022-05-26 22:11

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0009_rename_control_board_version_devicestatus_control_board_revision'),
    ]

    operations = [
        migrations.AddField(
            model_name='firmwareupdate',
            name='description',
            field=models.TextField(null=True),
        ),
    ]
