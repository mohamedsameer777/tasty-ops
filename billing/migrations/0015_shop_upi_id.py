from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0014_shop_logo_shop_latitude_shop_longitude_shop_address'),
    ]

    operations = [
        migrations.AddField(
            model_name='shop',
            name='upi_id',
            field=models.CharField(blank=True, max_length=100, help_text="Your UPI ID / VPA (e.g. yourname@okhdfcbank) — used to generate the GPay/UPI QR code at checkout."),
        ),
    ]