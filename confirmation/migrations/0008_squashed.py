from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    replaces = [('confirmation', '0001_initial'), ('confirmation', '0002_realmcreationkey'), ('confirmation', '0003_emailchangeconfirmation'), ('confirmation', '0004_remove_confirmationmanager'), ('confirmation', '0005_confirmation_realm'), ('confirmation', '0006_realmcreationkey_presume_email_valid'), ('confirmation', '0007_add_indexes')]

    initial = True

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.CreateModel(
            name='RealmCreationKey',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('creation_key', models.CharField(db_index=True, max_length=40, verbose_name='activation key')),
                ('date_created', models.DateTimeField(default=django.utils.timezone.now, verbose_name='created')),
                ('presume_email_valid', models.BooleanField(default=False)),
            ],
        ),
        migrations.CreateModel(
            name='Confirmation',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('object_id', models.PositiveIntegerField(db_index=True)),
                ('date_sent', models.DateTimeField(db_index=True)),
                ('confirmation_key', models.CharField(db_index=True, max_length=40)),
                ('type', models.PositiveSmallIntegerField()),
                ('content_type', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='contenttypes.ContentType')),
            ],
        ),
    ]
