# Generated by Django 3.2.8 on 2021-11-01 08:40

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("zerver", "0393_realm_want_advertise_in_communities_directory"),
    ]

    operations = [
        migrations.AddField(
            model_name="realmuserdefault",
            name="narrow_mode",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="narrow_mode",
            field=models.BooleanField(default=False),
        ),
    ]
