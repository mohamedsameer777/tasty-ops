from django.db import migrations, models


def backfill_bill_daily_numbers(apps, schema_editor):
    """Assign daily_number to bills that existed before this field did,
    grouped by shop and calendar date, in the order they were created."""
    Bill = apps.get_model('billing', 'Bill')
    from collections import defaultdict
    counters = defaultdict(int)
    for bill in Bill.objects.select_related('order').order_by('created_at'):
        key = (bill.order.shop_id, bill.created_at.date())
        counters[key] += 1
        bill.daily_number = counters[key]
        bill.save(update_fields=['daily_number'])


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0019_shop_youtube_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='bill',
            name='daily_number',
            field=models.PositiveIntegerField(blank=True, editable=False, null=True, help_text="A clean, human-friendly bill number that resets to 1 each day (e.g. 'Bill 3') — separate from the database id."),
        ),
        migrations.RunPython(backfill_bill_daily_numbers, migrations.RunPython.noop),
    ]