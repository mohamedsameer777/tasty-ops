from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0016_menuitem_image'),
    ]

    operations = [
        migrations.AddField(
            model_name='shop',
            name='google_review_url',
            field=models.URLField(blank=True, max_length=500, help_text="Your shop's Google Maps review link — added to the WhatsApp bill message so customers can leave a review."),
        ),
        migrations.AddField(
            model_name='shop',
            name='instagram_url',
            field=models.URLField(blank=True, max_length=300, help_text="Your shop's Instagram profile link — added to the WhatsApp bill message."),
        ),
    ]