# Generated by Django 3.2.9 on 2022-05-17 21:02

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0019_feedermodel_hopper_capacity'),
    ]

    operations = [
        migrations.AddField(
            model_name='deviceowner',
            name='manual_portion_size',
            field=models.FloatField(default=0.25),
        ),
    ]
