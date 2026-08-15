from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0015_shop_upi_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='menuitem',
            name='image',
            field=models.ImageField(blank=True, null=True, upload_to='menu_item_images/', help_text="Photo shown on the ordering screen so staff can find the item quickly."),
        ),
    ]