# Generated by Django 4.0.4 on 2022-05-26 19:33

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0005_controlboardmodel_firmwareupdate'),
    ]

    operations = [
        migrations.AddField(
            model_name='devicestatus',
            name='firmware_version',
            field=models.CharField(max_length=7, null=True),
        ),
    ]