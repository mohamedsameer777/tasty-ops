from django.core.management.base import BaseCommand
from django.db import transaction

from billing.models import Bill, Order
from billing.sales_summary import SYNTHETIC_ORDER_TAG

from ._shop_utils import add_shop_argument, resolve_shop


class Command(BaseCommand):
    help = (
        "Deletes the demo orders/bills created by generate_synthetic_sales (the ones tagged "
        "'synthetic') so every report and forecast is built from real sales only. "
        "Real orders are never touched. Does a dry run unless you pass --confirm."
    )

    def add_arguments(self, parser):
        add_shop_argument(parser)
        parser.add_argument('--confirm', action='store_true', help="Actually delete. Without this it only reports what it would delete.")

    def handle(self, *args, **options):
        shop = resolve_shop(options)
        orders = Order.objects.filter(shop=shop, table_or_token=SYNTHETIC_ORDER_TAG)
        order_count = orders.count()
        bill_count = Bill.objects.filter(order__in=orders).count()

        self.stdout.write(f"{shop.name}: {order_count} synthetic order(s), {bill_count} synthetic bill(s) found.")
        if not order_count:
            self.stdout.write(self.style.SUCCESS("Nothing to remove - no demo data."))
            return
        if not options['confirm']:
            self.stdout.write(self.style.WARNING("Dry run - nothing deleted. Re-run with --confirm to delete them."))
            return

        with transaction.atomic():
            Bill.objects.filter(order__in=orders).delete()   # Bill.order is PROTECT, so bills go first
            orders.delete()                                   # order items cascade
        self.stdout.write(self.style.SUCCESS(f"Deleted {order_count} synthetic order(s) and {bill_count} bill(s)."))