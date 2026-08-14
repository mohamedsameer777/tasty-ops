import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from billing.models import Bill, MenuItem, Order, OrderItem

from ._shop_utils import add_shop_argument, resolve_shop


class Command(BaseCommand):
    help = (
        "Backfills synthetic historical orders/bills for one shop so the forecasting "
        "pipeline has something to train on. Does NOT touch ingredient stock — "
        "this is purely to bootstrap sales history, not a real day's business. "
        "Swap this out once you have a few weeks of real billing data."
    )

    def add_arguments(self, parser):
        add_shop_argument(parser)
        parser.add_argument('--days', type=int, default=60, help="How many past days to backfill (default 60).")
        parser.add_argument('--seed', type=int, default=42, help="Random seed, for reproducible test data.")

    def handle(self, *args, **options):
        shop = resolve_shop(options)
        days = options['days']
        random.seed(options['seed'])

        menu_items = list(MenuItem.objects.filter(shop=shop, is_active=True))
        if not menu_items:
            self.stdout.write(self.style.ERROR(
                f"No active menu items found for {shop.name}. Add at least one via /api/menu-items/ first."
            ))
            return

        today = date.today()
        created_bills = 0

        for offset in range(days, 0, -1):
            sale_date = today - timedelta(days=offset)
            is_weekend = sale_date.weekday() in (5, 6)

            for menu_item in menu_items:
                # Base demand with weekend boost and random day-to-day noise.
                # Not every item sells every day — small chance of a zero-sale day.
                if random.random() < 0.08:
                    continue

                base = random.randint(3, 12)
                if is_weekend:
                    base = int(base * random.uniform(1.3, 1.8))
                quantity = max(1, base + random.randint(-2, 2))

                naive_dt = timezone.make_aware(
                    timezone.datetime.combine(sale_date, timezone.datetime.min.time()) + timedelta(hours=random.randint(10, 21))
                )

                order = Order.objects.create(shop=shop, status=Order.Status.OPEN, table_or_token='synthetic')
                Order.objects.filter(pk=order.pk).update(created_at=naive_dt, updated_at=naive_dt)

                order_item = OrderItem.objects.create(
                    order=order, menu_item=menu_item, quantity=quantity, unit_price=menu_item.price,
                )

                subtotal = order_item.unit_price * order_item.quantity
                bill = Bill.objects.create(
                    order=order, subtotal=subtotal, tax_rate=Decimal('0.00'),
                    tax_amount=Decimal('0.00'), total=subtotal,
                )
                Bill.objects.filter(pk=bill.pk).update(created_at=naive_dt)
                Order.objects.filter(pk=order.pk).update(status=Order.Status.BILLED)
                created_bills += 1

        self.stdout.write(self.style.SUCCESS(
            f"Created {created_bills} synthetic bills across {days} days for {len(menu_items)} menu item(s) — {shop.name}."
        ))
