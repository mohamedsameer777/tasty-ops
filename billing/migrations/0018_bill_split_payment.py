from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0017_shop_google_review_url_shop_instagram_url'),
    ]

    operations = [
        migrations.AlterField(
            model_name='bill',
            name='payment_method',
            field=models.CharField(
                choices=[('cash', 'Cash'), ('upi', 'GPay / UPI'), ('split', 'Split (Cash + GPay)'), ('other', 'Other')],
                default='cash', max_length=10,
                help_text="How the customer paid — used for the end-of-day cash/UPI audit split.",
            ),
        ),
        migrations.AddField(
            model_name='bill',
            name='cash_amount',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, help_text="Only set for split payments — how much of the total was paid in cash."),
        ),
        migrations.AddField(
            model_name='bill',
            name='upi_amount',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, help_text="Only set for split payments — how much of the total was paid via GPay/UPI."),
        ),
    ]