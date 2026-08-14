from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0012_shop_required'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='customer_name',
            field=models.CharField(blank=True, max_length=100, help_text="Optional — used on the receipt and for WhatsApp bill sharing."),
        ),
        migrations.AddField(
            model_name='order',
            name='customer_phone',
            field=models.CharField(blank=True, max_length=20, help_text="Optional. Include country code if sending WhatsApp, e.g. 919876543210."),
        ),
    ]