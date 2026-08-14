from django.db import migrations


def backfill_shop(apps, schema_editor):
    Shop = apps.get_model('billing', 'Shop')
    Membership = apps.get_model('billing', 'Membership')
    User = apps.get_model('auth', 'User')

    MenuItem = apps.get_model('billing', 'MenuItem')
    Order = apps.get_model('billing', 'Order')
    Ingredient = apps.get_model('billing', 'Ingredient')
    DemandForecast = apps.get_model('billing', 'DemandForecast')
    AgentLog = apps.get_model('billing', 'AgentLog')
    DemandAnomaly = apps.get_model('billing', 'DemandAnomaly')
    WeeklySummaryReport = apps.get_model('billing', 'WeeklySummaryReport')

    # Nothing to do on a brand-new install with no pre-existing data.
    has_existing_data = MenuItem.objects.exists() or Ingredient.objects.exists() or Order.objects.exists()
    if not has_existing_data:
        return

    shop, _ = Shop.objects.get_or_create(
        slug='tasty-zone',
        defaults={'name': 'Tasty Zone', 'contact_phone': '', 'contact_email': ''},
    )

    MenuItem.objects.filter(shop__isnull=True).update(shop=shop)
    Order.objects.filter(shop__isnull=True).update(shop=shop)
    Ingredient.objects.filter(shop__isnull=True).update(shop=shop)
    DemandForecast.objects.filter(shop__isnull=True).update(shop=shop)
    AgentLog.objects.filter(shop__isnull=True).update(shop=shop)
    DemandAnomaly.objects.filter(shop__isnull=True).update(shop=shop)
    WeeklySummaryReport.objects.filter(shop__isnull=True).update(shop=shop)

    # Link every existing non-superuser login to this shop so nobody gets
    # locked out after upgrading. Superusers keep full cross-shop access via
    # /admin/ regardless of membership.
    for user in User.objects.filter(is_superuser=False):
        Membership.objects.get_or_create(user=user, defaults={'shop': shop, 'role': 'owner'})

    # If there's no non-superuser account at all (e.g. only a superuser was
    # ever created), still give the first superuser a membership so they can
    # use the regular billing/dashboard pages, not just /admin/.
    if not Membership.objects.exists():
        first_user = User.objects.order_by('id').first()
        if first_user:
            Membership.objects.get_or_create(user=first_user, defaults={'shop': shop, 'role': 'owner'})


def noop_reverse(apps, schema_editor):
    # Not reversible in a meaningful way — leaving data in place is safer
    # than deleting it on a downgrade.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0010_tenancy'),
    ]

    operations = [
        migrations.RunPython(backfill_shop, noop_reverse),
    ]
