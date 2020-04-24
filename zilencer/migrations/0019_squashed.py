from django.conf import settings
from django.db import migrations
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    replaces = [('zilencer', '0001_initial'), ('zilencer', '0002_remote_zulip_server'), ('zilencer', '0003_add_default_for_remotezulipserver_last_updated_field'), ('zilencer', '0004_remove_deployment_model'), ('zilencer', '0005_remotepushdevicetoken_fix_uniqueness'), ('zilencer', '0006_customer'), ('zilencer', '0007_remotezulipserver_fix_uniqueness'), ('zilencer', '0008_customer_billing_user'), ('zilencer', '0009_plan'), ('zilencer', '0010_billingprocessor'), ('zilencer', '0011_customer_has_billing_relationship'), ('zilencer', '0012_coupon'), ('zilencer', '0013_remove_customer_billing_user'), ('zilencer', '0014_cleanup_pushdevicetoken'), ('zilencer', '0015_delete_billing'), ('zilencer', '0016_remote_counts'), ('zilencer', '0017_installationcount_indexes'), ('zilencer', '0018_remoterealmauditlog')]

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='RemoteZulipServer',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('uuid', models.CharField(max_length=36, unique=True)),
                ('api_key', models.CharField(max_length=64)),
                ('hostname', models.CharField(max_length=128)),
                ('contact_email', models.EmailField(blank=True, max_length=254)),
                ('last_updated', models.DateTimeField(auto_now=True, verbose_name='last updated')),
            ],
        ),
        migrations.CreateModel(
            name='RemoteRealmAuditLog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_time', models.DateTimeField(db_index=True)),
                ('backfilled', models.BooleanField(default=False)),
                ('extra_data', models.TextField(null=True)),
                ('event_type', models.PositiveSmallIntegerField()),
                ('realm_id', models.IntegerField(db_index=True)),
                ('remote_id', models.IntegerField(db_index=True)),
                ('server', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zilencer.RemoteZulipServer')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='RemoteRealmCount',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('property', models.CharField(max_length=32)),
                ('subgroup', models.CharField(max_length=16, null=True)),
                ('end_time', models.DateTimeField()),
                ('value', models.BigIntegerField()),
                ('realm_id', models.IntegerField(db_index=True)),
                ('remote_id', models.IntegerField(db_index=True)),
                ('server', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zilencer.RemoteZulipServer')),
            ],
            options={
                'unique_together': {('server', 'realm_id', 'property', 'subgroup', 'end_time')},
                'index_together': {('property', 'end_time'), ('server', 'remote_id')},
            },
        ),
        migrations.CreateModel(
            name='RemotePushDeviceToken',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.PositiveSmallIntegerField(choices=[(1, 'apns'), (2, 'gcm')])),
                ('token', models.CharField(db_index=True, max_length=4096)),
                ('last_updated', models.DateTimeField(auto_now=True)),
                ('ios_app_id', models.TextField(null=True)),
                ('user_id', models.BigIntegerField(db_index=True)),
                ('server', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zilencer.RemoteZulipServer')),
            ],
            options={
                'unique_together': {('server', 'user_id', 'kind', 'token')},
            },
        ),
        migrations.CreateModel(
            name='RemoteInstallationCount',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('property', models.CharField(max_length=32)),
                ('subgroup', models.CharField(max_length=16, null=True)),
                ('end_time', models.DateTimeField()),
                ('value', models.BigIntegerField()),
                ('remote_id', models.IntegerField(db_index=True)),
                ('server', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zilencer.RemoteZulipServer')),
            ],
            options={
                'unique_together': {('server', 'property', 'subgroup', 'end_time')},
                'index_together': {('server', 'remote_id')},
            },
        ),
    ]
