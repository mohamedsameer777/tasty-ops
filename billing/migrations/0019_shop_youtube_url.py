from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0018_bill_split_payment'),
    ]

    operations = [
        migrations.AddField(
            model_name='shop',
            name='youtube_url',
            field=models.URLField(blank=True, max_length=300, help_text="Your shop's YouTube channel link — added to the WhatsApp bill message."),
        ),
    ]