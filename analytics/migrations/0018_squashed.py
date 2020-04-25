from django.conf import settings
from django.db import migrations
from django.db import migrations, models
from django.db.backends.postgresql_psycopg2.schema import DatabaseSchemaEditor
from django.db.migrations.state import StateApps
from django.db.models import Count, Sum
import django.db.models.deletion


def delete_messages_sent_to_stream_stat(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserCount = apps.get_model('analytics', 'UserCount')
    StreamCount = apps.get_model('analytics', 'StreamCount')
    RealmCount = apps.get_model('analytics', 'RealmCount')
    InstallationCount = apps.get_model('analytics', 'InstallationCount')
    FillState = apps.get_model('analytics', 'FillState')

    property = 'messages_sent_to_stream:is_bot'
    UserCount.objects.filter(property=property).delete()
    StreamCount.objects.filter(property=property).delete()
    RealmCount.objects.filter(property=property).delete()
    InstallationCount.objects.filter(property=property).delete()
    FillState.objects.filter(property=property).delete()


def clear_message_sent_by_message_type_values(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserCount = apps.get_model('analytics', 'UserCount')
    StreamCount = apps.get_model('analytics', 'StreamCount')
    RealmCount = apps.get_model('analytics', 'RealmCount')
    InstallationCount = apps.get_model('analytics', 'InstallationCount')
    FillState = apps.get_model('analytics', 'FillState')

    property = 'messages_sent:message_type:day'
    UserCount.objects.filter(property=property).delete()
    StreamCount.objects.filter(property=property).delete()
    RealmCount.objects.filter(property=property).delete()
    InstallationCount.objects.filter(property=property).delete()
    FillState.objects.filter(property=property).delete()


def clear_analytics_tables(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserCount = apps.get_model('analytics', 'UserCount')
    StreamCount = apps.get_model('analytics', 'StreamCount')
    RealmCount = apps.get_model('analytics', 'RealmCount')
    InstallationCount = apps.get_model('analytics', 'InstallationCount')
    FillState = apps.get_model('analytics', 'FillState')

    UserCount.objects.all().delete()
    StreamCount.objects.all().delete()
    RealmCount.objects.all().delete()
    InstallationCount.objects.all().delete()
    FillState.objects.all().delete()


def clear_duplicate_counts(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    """This is a preparatory migration for our Analytics tables.

    The backstory is that Django's unique_together indexes do not properly
    handle the subgroup=None corner case (allowing duplicate rows that have a
    subgroup of None), which meant that in race conditions, rather than updating
    an existing row for the property/realm/time with subgroup=None, Django would
    create a duplicate row.

    In the next migration, we'll add a proper constraint to fix this bug, but
    we need to fix any existing problematic rows before we can add that constraint.

    We fix this in an appropriate fashion for each type of CountStat object; mainly
    this means deleting the extra rows, but for LoggingCountStat objects, we need to
    additionally combine the sums.
    """
    RealmCount = apps.get_model('analytics', 'RealmCount')

    realm_counts = RealmCount.objects.filter(subgroup=None).values(
        'realm_id', 'property', 'end_time').annotate(
            Count('id'), Sum('value')).filter(id__count__gt=1)

    for realm_count in realm_counts:
        realm_count.pop('id__count')
        total_value = realm_count.pop('value__sum')
        duplicate_counts = list(RealmCount.objects.filter(**realm_count))
        first_count = duplicate_counts[0]
        if realm_count['property'] in ["invites_sent::day", "active_users_log:is_bot:day"]:
            # For LoggingCountStat objects, the right fix is to combine the totals;
            # for other CountStat objects, we expect the duplicates to have the same value.
            # And so all we need to do is delete them.
            first_count.value = total_value
            first_count.save()
        to_cleanup = duplicate_counts[1:]
        for duplicate_count in to_cleanup:
            duplicate_count.delete()


    @staticmethod
    def noop(apps, schema_editor):
        return None


def delete_messages_sent_to_stream_stat_2(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserCount = apps.get_model('analytics', 'UserCount')
    StreamCount = apps.get_model('analytics', 'StreamCount')
    RealmCount = apps.get_model('analytics', 'RealmCount')
    InstallationCount = apps.get_model('analytics', 'InstallationCount')
    FillState = apps.get_model('analytics', 'FillState')

    property = 'messages_sent_to_stream:is_bot'
    UserCount.objects.filter(property=property).delete()
    StreamCount.objects.filter(property=property).delete()
    RealmCount.objects.filter(property=property).delete()
    InstallationCount.objects.filter(property=property).delete()
    FillState.objects.filter(property=property).delete()


def clear_message_sent_by_message_type_values_2(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserCount = apps.get_model('analytics', 'UserCount')
    StreamCount = apps.get_model('analytics', 'StreamCount')
    RealmCount = apps.get_model('analytics', 'RealmCount')
    InstallationCount = apps.get_model('analytics', 'InstallationCount')
    FillState = apps.get_model('analytics', 'FillState')

    property = 'messages_sent:message_type:day'
    UserCount.objects.filter(property=property).delete()
    StreamCount.objects.filter(property=property).delete()
    RealmCount.objects.filter(property=property).delete()
    InstallationCount.objects.filter(property=property).delete()
    FillState.objects.filter(property=property).delete()


def clear_analytics_tables_2(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    UserCount = apps.get_model('analytics', 'UserCount')
    StreamCount = apps.get_model('analytics', 'StreamCount')
    RealmCount = apps.get_model('analytics', 'RealmCount')
    InstallationCount = apps.get_model('analytics', 'InstallationCount')
    FillState = apps.get_model('analytics', 'FillState')

    UserCount.objects.all().delete()
    StreamCount.objects.all().delete()
    RealmCount.objects.all().delete()
    InstallationCount.objects.all().delete()
    FillState.objects.all().delete()


def clear_duplicate_counts_2(apps: StateApps, schema_editor: DatabaseSchemaEditor) -> None:
    """This is a preparatory migration for our Analytics tables.

    The backstory is that Django's unique_together indexes do not properly
    handle the subgroup=None corner case (allowing duplicate rows that have a
    subgroup of None), which meant that in race conditions, rather than updating
    an existing row for the property/realm/time with subgroup=None, Django would
    create a duplicate row.

    In the next migration, we'll add a proper constraint to fix this bug, but
    we need to fix any existing problematic rows before we can add that constraint.

    We fix this in an appropriate fashion for each type of CountStat object; mainly
    this means deleting the extra rows, but for LoggingCountStat objects, we need to
    additionally combine the sums.
    """
    RealmCount = apps.get_model('analytics', 'RealmCount')

    realm_counts = RealmCount.objects.filter(subgroup=None).values(
        'realm_id', 'property', 'end_time').annotate(
            Count('id'), Sum('value')).filter(id__count__gt=1)

    for realm_count in realm_counts:
        realm_count.pop('id__count')
        total_value = realm_count.pop('value__sum')
        duplicate_counts = list(RealmCount.objects.filter(**realm_count))
        first_count = duplicate_counts[0]
        if realm_count['property'] in ["invites_sent::day", "active_users_log:is_bot:day"]:
            # For LoggingCountStat objects, the right fix is to combine the totals;
            # for other CountStat objects, we expect the duplicates to have the same value.
            # And so all we need to do is delete them.
            first_count.value = total_value
            first_count.save()
        to_cleanup = duplicate_counts[1:]
        for duplicate_count in to_cleanup:
            duplicate_count.delete()


    @staticmethod
    def noop(apps, schema_editor):
        return None


class Migration(migrations.Migration):

    replaces = [('analytics', '0001_initial'), ('analytics', '0002_remove_huddlecount'), ('analytics', '0003_fillstate'), ('analytics', '0004_add_subgroup'), ('analytics', '0005_alter_field_size'), ('analytics', '0006_add_subgroup_to_unique_constraints'), ('analytics', '0007_remove_interval'), ('analytics', '0008_add_count_indexes'), ('analytics', '0009_remove_messages_to_stream_stat'), ('analytics', '0010_clear_messages_sent_values'), ('analytics', '0011_clear_analytics_tables'), ('analytics', '0012_add_on_delete'), ('analytics', '0013_remove_anomaly'), ('analytics', '0014_remove_fillstate_last_modified'), ('analytics', '0015_clear_duplicate_counts'), ('analytics', '0016_unique_constraint_when_subgroup_null')]

    initial = True

    dependencies = [
        ('zerver', '0273_squashed'),
        ('zerver', '0273_squashed'),
        ('analytics', '0017_squashed'),
    ]

    operations = [
        migrations.AddField(
            model_name='usercount',
            name='realm',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm'),
        ),
        migrations.AddField(
            model_name='usercount',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='streamcount',
            name='realm',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm'),
        ),
        migrations.AddField(
            model_name='streamcount',
            name='stream',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Stream'),
        ),
        migrations.AddField(
            model_name='realmcount',
            name='realm',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm'),
        ),
        migrations.AddConstraint(
            model_name='installationcount',
            constraint=models.UniqueConstraint(condition=models.Q(subgroup__isnull=False), fields=('property', 'subgroup', 'end_time'), name='unique_installation_count'),
        ),
        migrations.AddConstraint(
            model_name='installationcount',
            constraint=models.UniqueConstraint(condition=models.Q(subgroup__isnull=True), fields=('property', 'end_time'), name='unique_installation_count_null_subgroup'),
        ),
        migrations.AddConstraint(
            model_name='usercount',
            constraint=models.UniqueConstraint(condition=models.Q(subgroup__isnull=False), fields=('user', 'property', 'subgroup', 'end_time'), name='unique_user_count'),
        ),
        migrations.AddConstraint(
            model_name='usercount',
            constraint=models.UniqueConstraint(condition=models.Q(subgroup__isnull=True), fields=('user', 'property', 'end_time'), name='unique_user_count_null_subgroup'),
        ),
        migrations.AlterIndexTogether(
            name='usercount',
            index_together={('property', 'realm', 'end_time')},
        ),
        migrations.AddConstraint(
            model_name='streamcount',
            constraint=models.UniqueConstraint(condition=models.Q(subgroup__isnull=False), fields=('stream', 'property', 'subgroup', 'end_time'), name='unique_stream_count'),
        ),
        migrations.AddConstraint(
            model_name='streamcount',
            constraint=models.UniqueConstraint(condition=models.Q(subgroup__isnull=True), fields=('stream', 'property', 'end_time'), name='unique_stream_count_null_subgroup'),
        ),
        migrations.AlterIndexTogether(
            name='streamcount',
            index_together={('property', 'realm', 'end_time')},
        ),
        migrations.AddConstraint(
            model_name='realmcount',
            constraint=models.UniqueConstraint(condition=models.Q(subgroup__isnull=False), fields=('realm', 'property', 'subgroup', 'end_time'), name='unique_realm_count'),
        ),
        migrations.AddConstraint(
            model_name='realmcount',
            constraint=models.UniqueConstraint(condition=models.Q(subgroup__isnull=True), fields=('realm', 'property', 'end_time'), name='unique_realm_count_null_subgroup'),
        ),
        migrations.AlterIndexTogether(
            name='realmcount',
            index_together={('property', 'end_time')},
        ),
        migrations.RunPython(
            code=delete_messages_sent_to_stream_stat,
            elidable=False,
        ),
        migrations.RunPython(
            code=clear_message_sent_by_message_type_values,
            elidable=False,
        ),
        migrations.RunPython(
            code=clear_analytics_tables,
            elidable=False,
        ),
        migrations.RunPython(
            code=clear_duplicate_counts,
            reverse_code=RunPython.noop,
            elidable=False,
        ),
        migrations.RunPython(
            code=delete_messages_sent_to_stream_stat_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=clear_message_sent_by_message_type_values_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=clear_analytics_tables_2,
            elidable=False,
        ),
        migrations.RunPython(
            code=clear_duplicate_counts_2,
            reverse_code=RunPython.noop,
            elidable=False,
        ),
    ]
