from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    replaces = [('corporate', '0001_initial'), ('corporate', '0002_customer_default_discount'), ('corporate', '0003_customerplan'), ('corporate', '0004_licenseledger'), ('corporate', '0005_customerplan_invoicing'), ('corporate', '0006_nullable_stripe_customer_id'), ('corporate', '0007_remove_deprecated_fields'), ('corporate', '0008_nullable_next_invoice_date')]

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Customer',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stripe_customer_id', models.CharField(max_length=255, null=True, unique=True)),
                ('default_discount', models.DecimalField(decimal_places=4, max_digits=7, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='CustomerPlan',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('automanage_licenses', models.BooleanField(default=False)),
                ('charge_automatically', models.BooleanField(default=False)),
                ('price_per_license', models.IntegerField(null=True)),
                ('fixed_price', models.IntegerField(null=True)),
                ('discount', models.DecimalField(decimal_places=4, max_digits=6, null=True)),
                ('billing_cycle_anchor', models.DateTimeField()),
                ('billing_schedule', models.SmallIntegerField()),
                ('next_invoice_date', models.DateTimeField(db_index=True, null=True)),
                ('invoicing_status', models.SmallIntegerField(default=1)),
                ('tier', models.SmallIntegerField()),
                ('status', models.SmallIntegerField(default=1)),
                ('customer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='corporate.Customer')),
            ],
        ),
        migrations.CreateModel(
            name='LicenseLedger',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_renewal', models.BooleanField(default=False)),
                ('event_time', models.DateTimeField()),
                ('licenses', models.IntegerField()),
                ('licenses_at_next_renewal', models.IntegerField(null=True)),
                ('plan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='corporate.CustomerPlan')),
            ],
        ),
        migrations.AddField(
            model_name='customerplan',
            name='invoiced_through',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='corporate.LicenseLedger'),
        ),
    ]
