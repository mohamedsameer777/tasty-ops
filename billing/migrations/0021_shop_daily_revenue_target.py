from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0020_bill_daily_number'),
    ]

    operations = [
        migrations.AddField(
            model_name='shop',
            name='daily_revenue_target',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, help_text="Optional. A daily revenue goal — shown as a progress bar on the dashboard, with a streak counter for consecutive days hit."),
        ),
    ]