# Generated by Django 4.2.16 on 2024-10-28 13:44

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('mpesa_express', '0002_transaction_mpesa_code'),
    ]

    operations = [
        migrations.AlterField(
            model_name='transaction',
            name='amount',
            field=models.DecimalField(decimal_places=2, max_digits=10),
        ),
        migrations.AlterField(
            model_name='transaction',
            name='mpesa_code',
            field=models.CharField(default=django.utils.timezone.now, max_length=100, unique=True),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='transaction',
            name='status',
            field=models.CharField(max_length=20),
        ),
    ]
