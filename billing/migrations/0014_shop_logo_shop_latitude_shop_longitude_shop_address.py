from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0013_order_customer_name_order_customer_phone'),
    ]

    operations = [
        migrations.AddField(
            model_name='shop',
            name='logo',
            field=models.ImageField(blank=True, null=True, upload_to='shop_logos/', help_text="Shown at the top of the billing screen and on receipts."),
        ),
        migrations.AddField(
            model_name='shop',
            name='latitude',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True, help_text="Auto-filled from the owner's device location."),
        ),
        migrations.AddField(
            model_name='shop',
            name='longitude',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True, help_text="Auto-filled from the owner's device location."),
        ),
        migrations.AddField(
            model_name='shop',
            name='address',
            field=models.CharField(blank=True, max_length=255, help_text="Human-readable address, auto-filled from device location where possible."),
        ),
    ]