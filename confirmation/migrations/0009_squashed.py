from django.db import migrations
from django.db import models, migrations
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    replaces = [('confirmation', '0001_initial'), ('confirmation', '0002_realmcreationkey'), ('confirmation', '0003_emailchangeconfirmation'), ('confirmation', '0004_remove_confirmationmanager'), ('confirmation', '0005_confirmation_realm'), ('confirmation', '0006_realmcreationkey_presume_email_valid'), ('confirmation', '0007_add_indexes')]

    initial = True

    dependencies = [
        ('confirmation', '0008_squashed'),
        ('zerver', '0273_squashed'),
    ]

    operations = [
        migrations.AddField(
            model_name='confirmation',
            name='realm',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm'),
        ),
        migrations.AlterUniqueTogether(
            name='confirmation',
            unique_together={('type', 'confirmation_key')},
        ),
    ]
