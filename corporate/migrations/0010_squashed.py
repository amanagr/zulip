from django.db import migrations, models
from django.db import migrations
import django.db.models.deletion


class Migration(migrations.Migration):

    replaces = [('corporate', '0001_initial'), ('corporate', '0002_customer_default_discount'), ('corporate', '0003_customerplan'), ('corporate', '0004_licenseledger'), ('corporate', '0005_customerplan_invoicing'), ('corporate', '0006_nullable_stripe_customer_id'), ('corporate', '0007_remove_deprecated_fields'), ('corporate', '0008_nullable_next_invoice_date')]

    initial = True

    dependencies = [
        ('zerver', '0273_squashed'),
        ('corporate', '0009_squashed'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='realm',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='zerver.Realm'),
        ),
    ]
