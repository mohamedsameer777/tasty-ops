from types import SimpleNamespace

from django.test import SimpleTestCase

from .voice_parsing import parse_order_text


def _item(i, name, fried=False, cheese=False):
    return SimpleNamespace(id=i, name=name, supports_fried_option=fried, supports_cheese_option=cheese)


MENU = [
    _item(1, "Veg Patty Burger", cheese=True),
    _item(2, "Chicken Patty Burger", cheese=True),
    _item(3, "Fried Chicken Burger", cheese=True),
    _item(4, "Chicken Cheese Momo (6 PCS)", fried=True),
    _item(5, "Chicken Momo (6 PCS)", fried=True),
    _item(6, "Paneer Momo (6 PCS)", fried=True),
    _item(7, "Veg Momo (6 PCS)", fried=True),
    _item(8, "Chicken Lolipop (3 PCS)"),
    _item(9, "Crab Lolipop (4 PCS)"),
    _item(10, "French Fries"),
    _item(11, "Peri Peri French Fries"),
]


def parse(text):
    return [
        (r['quantity'], r['menu_item'].name if r['menu_item'] else None, r['review_reason'])
        for r in parse_order_text(text, MENU)
    ]


class VoiceParsingTests(SimpleTestCase):
    def test_several_items_without_and_or_commas(self):
        # Speech-to-text gives no separators - this used to add only ONE item.
        self.assertEqual(parse("two chicken momo one veg momo"), [
            (2, "Chicken Momo (6 PCS)", None), (1, "Veg Momo (6 PCS)", None)])

    def test_digits_and_modifiers(self):
        res = parse_order_text("2 chicken momos 1 paneer momo fried 3 french fries", MENU)
        self.assertEqual([(r['quantity'], r['menu_item'].name, r['is_fried']) for r in res], [
            (2, "Chicken Momo (6 PCS)", False), (1, "Paneer Momo (6 PCS)", True), (3, "French Fries", False)])

    def test_dish_names_containing_cheese_or_fried(self):
        self.assertEqual(parse("two chicken cheese momo")[0][1], "Chicken Cheese Momo (6 PCS)")
        self.assertEqual(parse("fried chicken burger")[0][1], "Fried Chicken Burger")

    def test_ambiguous_dish_is_not_guessed(self):
        (qty, name, reason), = parse("chicken burger")
        self.assertEqual(reason, 'ambiguous')
        res = parse_order_text("chicken burger", MENU)[0]
        self.assertGreaterEqual(len(res['suggestions']), 2)

    def test_mishearings(self):
        self.assertEqual(parse("two mo mo chicken")[0][:2], (2, "Chicken Momo (6 PCS)"))
        self.assertEqual(parse("chiken mamos")[0][:2], (1, "Chicken Momo (6 PCS)"))

    def test_trailing_quantity_and_x_style(self):
        self.assertEqual(parse("chicken lollipop two")[0][:2], (2, "Chicken Lolipop (3 PCS)"))
        self.assertEqual([p[0] for p in parse("veg momo x2 and french fries x3")], [2, 3])

    def test_size_is_not_a_quantity(self):
        self.assertEqual(parse("chicken momo 6 pieces")[0][:2], (1, "Chicken Momo (6 PCS)"))

    def test_parcel_applies_where_said(self):
        res = parse_order_text("two chicken momo and one veg momo parcel", MENU)
        self.assertEqual([r['is_parcel'] for r in res], [False, True])
        res = parse_order_text("two chicken momo one veg momo all parcel", MENU)
        self.assertEqual([r['is_parcel'] for r in res], [True, True])

    def test_nonsense_never_crashes_or_auto_adds(self):
        self.assertEqual(parse(""), [])
        self.assertEqual(parse("cancel"), [])
        (qty, name, reason), = parse("two pizza")
        self.assertEqual((name, reason), (None, 'low_match'))