# Generated by Django 4.0.4 on 2022-05-24 22:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='pet',
            name='photo',
            field=models.FileField(null=True, upload_to='pet_photos/'),
        ),
    ]
