from decimal import Decimal

from django.core.management.base import BaseCommand

from billing.models import MenuItem

from ._shop_utils import add_shop_argument, resolve_shop


# (name, category, price, supports_fried_option, supports_cheese_option)
TASTY_ZONE_MENU = [
    # Burgers — cheese is a +₹20 optional add-on for any of these
    ("Veg Patty Burger", MenuItem.Category.BURGER, "100.00", False, True),
    ("Paneer Fried Momos Burger", MenuItem.Category.BURGER, "110.00", False, True),
    ("Chicken Patty Burger", MenuItem.Category.BURGER, "110.00", False, True),
    ("Chicken Fried Momos Burger", MenuItem.Category.BURGER, "110.00", False, True),
    ("Fried Chicken Burger", MenuItem.Category.BURGER, "130.00", False, True),

    # Momos — fried is a +₹20 optional add-on for any of these
    ("Chicken Cheese Momo (6 PCS)", MenuItem.Category.MOMO, "130.00", True, False),
    ("Chicken Peri Peri Momo (6 PCS)", MenuItem.Category.MOMO, "120.00", True, False),
    ("Chicken Tikka Momo (6 PCS)", MenuItem.Category.MOMO, "120.00", True, False),
    ("Chicken Momo (6 PCS)", MenuItem.Category.MOMO, "110.00", True, False),
    ("Corn Cheese Momo (6 PCS)", MenuItem.Category.MOMO, "130.00", True, False),
    ("Paneer Momo (6 PCS)", MenuItem.Category.MOMO, "110.00", True, False),
    ("Veg Momo (6 PCS)", MenuItem.Category.MOMO, "100.00", True, False),

    # Home Made
    ("Lays Chicken", MenuItem.Category.HOME_MADE, "150.00", False, False),
    ("Chicken Popcorn (100 GRM)", MenuItem.Category.HOME_MADE, "130.00", False, False),
    ("Chicken Wings (3 PCS)", MenuItem.Category.HOME_MADE, "130.00", False, False),
    ("Chicken Lolipop (3 PCS)", MenuItem.Category.HOME_MADE, "130.00", False, False),
    ("Chicken Samosa (2 PCS)", MenuItem.Category.HOME_MADE, "50.00", False, False),
    ("Chicken Cutlet (2 PCS)", MenuItem.Category.HOME_MADE, "50.00", False, False),
    ("Chicken Loaded Fries", MenuItem.Category.HOME_MADE, "170.00", False, False),

    # Rolls
    ("Chicken Roll (2 PCS)", MenuItem.Category.ROLL, "80.00", False, False),
    ("Veg Roll (2 PCS)", MenuItem.Category.ROLL, "70.00", False, False),
    ("Paneer Roll (2 PCS)", MenuItem.Category.ROLL, "80.00", False, False),

    # Veg
    ("Peri Peri French Fries", MenuItem.Category.VEG, "80.00", False, False),
    ("French Fries", MenuItem.Category.VEG, "60.00", False, False),
    ("Veg Nuggets (8 PCS)", MenuItem.Category.VEG, "80.00", False, False),

    # Non Veg
    ("Chicken Nuggets (5 PCS)", MenuItem.Category.NON_VEG, "90.00", False, False),
    ("Chicken Cheese Balls (5 PCS)", MenuItem.Category.NON_VEG, "90.00", False, False),

    # Pasta
    ("White Sauce Pasta", MenuItem.Category.PASTA, "110.00", False, False),
    ("Red Sauce Pasta", MenuItem.Category.PASTA, "110.00", False, False),

    # Seafood
    ("Fish Fingers (4 PCS)", MenuItem.Category.SEAFOOD, "130.00", False, False),
    ("Crab Lolipop (4 PCS)", MenuItem.Category.SEAFOOD, "150.00", False, False),
    ("Crispy Prawn Bites (6 PCS)", MenuItem.Category.SEAFOOD, "120.00", False, False),
]


class Command(BaseCommand):
    help = "Loads (or updates) the real Tasty Zone menu with correct categories, prices, and modifier flags, for one shop."

    def add_arguments(self, parser):
        add_shop_argument(parser)

    def handle(self, *args, **options):
        shop = resolve_shop(options)
        created_count = 0
        updated_count = 0

        for name, category, price, fried, cheese in TASTY_ZONE_MENU:
            obj, created = MenuItem.objects.update_or_create(
                shop=shop,
                name=name,
                defaults={
                    'category': category,
                    'price': Decimal(price),
                    'supports_fried_option': fried,
                    'supports_cheese_option': cheese,
                    'is_active': True,
                },
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Menu loaded: {created_count} item(s) created, {updated_count} updated. "
            f"Total items in TASTY_ZONE_MENU: {len(TASTY_ZONE_MENU)}."
        ))
        self.stdout.write(
            "Reminder: parcel (+₹5/item) applies to any item and is chosen at billing time, "
            "not per menu item — no menu setup needed for that one."
        )