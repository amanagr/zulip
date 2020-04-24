from django.db import migrations, models


class Migration(migrations.Migration):

    replaces = [('analytics', '0001_initial'), ('analytics', '0002_remove_huddlecount'), ('analytics', '0003_fillstate'), ('analytics', '0004_add_subgroup'), ('analytics', '0005_alter_field_size'), ('analytics', '0006_add_subgroup_to_unique_constraints'), ('analytics', '0007_remove_interval'), ('analytics', '0008_add_count_indexes'), ('analytics', '0009_remove_messages_to_stream_stat'), ('analytics', '0010_clear_messages_sent_values'), ('analytics', '0011_clear_analytics_tables'), ('analytics', '0012_add_on_delete'), ('analytics', '0013_remove_anomaly'), ('analytics', '0014_remove_fillstate_last_modified'), ('analytics', '0015_clear_duplicate_counts'), ('analytics', '0016_unique_constraint_when_subgroup_null')]

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='FillState',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('property', models.CharField(max_length=40, unique=True)),
                ('end_time', models.DateTimeField()),
                ('state', models.PositiveSmallIntegerField()),
            ],
        ),
        migrations.CreateModel(
            name='InstallationCount',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('property', models.CharField(max_length=32)),
                ('subgroup', models.CharField(max_length=16, null=True)),
                ('end_time', models.DateTimeField()),
                ('value', models.BigIntegerField()),
            ],
        ),
        migrations.CreateModel(
            name='RealmCount',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('property', models.CharField(max_length=32)),
                ('subgroup', models.CharField(max_length=16, null=True)),
                ('end_time', models.DateTimeField()),
                ('value', models.BigIntegerField()),
            ],
        ),
        migrations.CreateModel(
            name='StreamCount',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('property', models.CharField(max_length=32)),
                ('subgroup', models.CharField(max_length=16, null=True)),
                ('end_time', models.DateTimeField()),
                ('value', models.BigIntegerField()),
            ],
        ),
        migrations.CreateModel(
            name='UserCount',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('property', models.CharField(max_length=32)),
                ('subgroup', models.CharField(max_length=16, null=True)),
                ('end_time', models.DateTimeField()),
                ('value', models.BigIntegerField()),
            ],
        ),
    ]
