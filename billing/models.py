from decimal import Decimal

from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator


class Shop(models.Model):
    """
    One tenant — one shop/stall using the platform. Everything else in this
    app (menu, orders, ingredients, forecasts, agent runs) belongs to
    exactly one Shop, so multiple shop owners can use the same deployment
    without ever seeing each other's data.
    """

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True, help_text="Used in URLs and as a stable internal identifier.")
    contact_phone = models.CharField(max_length=20, blank=True)
    contact_email = models.EmailField(blank=True)
    logo = models.ImageField(upload_to='shop_logos/', blank=True, null=True, help_text="Shown at the top of the billing screen and on receipts.")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, help_text="Auto-filled from the owner's device location.")
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, help_text="Auto-filled from the owner's device location.")
    address = models.CharField(max_length=255, blank=True, help_text="Human-readable address, auto-filled from device location where possible.")
    upi_id = models.CharField(max_length=100, blank=True, help_text="Your UPI ID / VPA (e.g. yourname@okhdfcbank) — used to generate the GPay/UPI QR code at checkout.")
    google_review_url = models.URLField(max_length=500, blank=True, help_text="Your shop's Google Maps review link — added to the WhatsApp bill message so customers can leave a review.")
    instagram_url = models.URLField(max_length=300, blank=True, help_text="Your shop's Instagram profile link — added to the WhatsApp bill message.")
    is_active = models.BooleanField(default=True, help_text="Turn off to suspend a shop's access without deleting its data.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Membership(models.Model):
    """
    Links a Django auth User to the one Shop they belong to. One membership
    per user for now (a user works at a single shop) — the role field is
    here so multi-staff-per-shop can be added later without a schema change.
    """

    class Role(models.TextChoices):
        OWNER = 'owner', 'Owner'
        STAFF = 'staff', 'Staff'

    user = models.OneToOneField(settings.AUTH_USER_MODEL, related_name='membership', on_delete=models.CASCADE)
    shop = models.ForeignKey(Shop, related_name='members', on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.OWNER)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} @ {self.shop.name} ({self.role})"


class MenuItem(models.Model):
    """A single item the stall sells (e.g. 'Chicken Momo (6 PCS)', 'French Fries')."""

    class Category(models.TextChoices):
        BURGER = 'burger', 'Burgers'
        MOMO = 'momo', 'Momos'
        HOME_MADE = 'home_made', 'Home Made'
        ROLL = 'roll', 'Rolls'
        VEG = 'veg', 'Veg'
        NON_VEG = 'non_veg', 'Non Veg'
        PASTA = 'pasta', 'Pasta'
        SEAFOOD = 'seafood', 'Seafood'
        OTHER = 'other', 'Other'

    shop = models.ForeignKey(Shop, related_name='menu_items', on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    price = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    cost_price = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Optional. What it costs you to make one unit — only used later for margin/wastage analysis, never required for billing. Leave 0 if you don't track this.",
    )
    image = models.ImageField(
        upload_to='menu_item_images/', blank=True, null=True,
        help_text="Photo shown on the ordering screen so staff can find the item quickly.",
    )
    supports_fried_option = models.BooleanField(
        default=False, help_text="Show a 'Fried? +₹20' choice when adding this item (e.g. for momos).",
    )
    supports_cheese_option = models.BooleanField(
        default=False, help_text="Show an 'Add cheese? +₹20' choice when adding this item (e.g. for burgers).",
    )
    is_active = models.BooleanField(default=True, help_text="Turn off instead of deleting when out of season/sold out for good.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'name']
        unique_together = ['shop', 'name']

    def __str__(self):
        return f"{self.name} (₹{self.price})"


class Order(models.Model):
    """One customer's order — a basket of items before it's finalized into a Bill."""

    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        BILLED = 'billed', 'Billed'
        CANCELLED = 'cancelled', 'Cancelled'

    shop = models.ForeignKey(Shop, related_name='orders', on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    table_or_token = models.CharField(
        max_length=50, blank=True,
        help_text="Optional table number or token/queue number for the order.",
    )
    customer_name = models.CharField(max_length=100, blank=True, help_text="Optional — used on the receipt and for WhatsApp bill sharing.")
    customer_phone = models.CharField(max_length=20, blank=True, help_text="Optional. Include country code if sending WhatsApp, e.g. 919876543210.")
    daily_number = models.PositiveIntegerField(
        editable=False, null=True, blank=True,
        help_text="A clean, human-friendly order number that resets to 1 each day (e.g. 'Order 3') — separate from the database id.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if self.pk is None and self.daily_number is None:
            from django.utils import timezone
            today = timezone.localdate()
            todays_count = Order.objects.filter(shop=self.shop, created_at__date=today).count()
            self.daily_number = todays_count + 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Order #{self.id} ({self.status})"

    @property
    def subtotal(self):
        return sum((item.line_total for item in self.items.all()), Decimal('0.00'))


class OrderItem(models.Model):
    """A single menu item + quantity + chosen modifiers within an order."""

    # Fixed shop-wide surcharges for modifiers.
    PARCEL_CHARGE = Decimal('5.00')
    FRIED_CHARGE = Decimal('20.00')
    CHEESE_CHARGE = Decimal('20.00')

    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    menu_item = models.ForeignKey(MenuItem, related_name='order_items', on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    is_parcel = models.BooleanField(default=False, help_text=f"Takeaway/parcel — adds ₹{PARCEL_CHARGE} per unit.")
    is_fried = models.BooleanField(default=False, help_text=f"Fried option — adds ₹{FRIED_CHARGE} per unit (only meaningful if the menu item supports it).")
    has_extra_cheese = models.BooleanField(default=False, help_text=f"Extra cheese — adds ₹{CHEESE_CHARGE} per unit (only meaningful if the menu item supports it).")
    unit_price = models.DecimalField(
        max_digits=8, decimal_places=2,
        help_text="Snapshot of MenuItem.price + any modifier surcharges at the time of order, so later price changes don't rewrite history.",
    )

    def compute_unit_price(self):
        price = self.menu_item.price
        if self.is_parcel:
            price += self.PARCEL_CHARGE
        if self.is_fried and self.menu_item.supports_fried_option:
            price += self.FRIED_CHARGE
        if self.has_extra_cheese and self.menu_item.supports_cheese_option:
            price += self.CHEESE_CHARGE
        return price

    def save(self, *args, **kwargs):
        if not self.unit_price:
            self.unit_price = self.compute_unit_price()
        super().save(*args, **kwargs)

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    @property
    def display_name(self):
        """Menu item name plus any active modifiers, for receipts and the order screen."""
        mods = []
        if self.is_fried:
            mods.append('Fried')
        if self.has_extra_cheese:
            mods.append('Extra Cheese')
        if self.is_parcel:
            mods.append('Parcel')
        if mods:
            return f"{self.menu_item.name} ({', '.join(mods)})"
        return self.menu_item.name

    def __str__(self):
        return f"{self.quantity} x {self.display_name}"


class Bill(models.Model):
    """A finalized, immutable bill generated from an Order."""

    class PaymentMethod(models.TextChoices):
        CASH = 'cash', 'Cash'
        UPI = 'upi', 'GPay / UPI'
        OTHER = 'other', 'Other'

    order = models.OneToOneField(Order, related_name='bill', on_delete=models.PROTECT)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    tax_rate = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('0.00'), help_text="e.g. 5.00 for 5% tax. Leave 0 to skip tax entirely.")
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices, default=PaymentMethod.CASH, help_text="How the customer paid — used for the end-of-day cash/UPI audit split.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Bill #{self.id} — ₹{self.total} ({self.created_at:%Y-%m-%d %H:%M})"


class Ingredient(models.Model):
    """A raw stock item you buy from a supplier (e.g. chicken, oil, rice)."""

    class Unit(models.TextChoices):
        GRAM = 'g', 'Grams'
        KILOGRAM = 'kg', 'Kilograms'
        MILLILITRE = 'ml', 'Millilitres'
        LITRE = 'l', 'Litres'
        PIECE = 'pcs', 'Pieces'

    shop = models.ForeignKey(Shop, related_name='ingredients', on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    unit = models.CharField(max_length=5, choices=Unit.choices, default=Unit.GRAM)
    current_stock = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Current quantity on hand, in the unit above.",
    )
    reorder_threshold = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        help_text="When current_stock drops to/below this, it's considered low stock.",
    )
    supplier_contact = models.CharField(max_length=100, blank=True, help_text="Supplier's name or general contact info.")
    supplier_whatsapp = models.CharField(
        max_length=20, blank=True,
        help_text="Supplier's WhatsApp number in E.164 format, e.g. +919876543210. Used by the reorder agent to send messages directly.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        unique_together = ['shop', 'name']

    def __str__(self):
        return f"{self.name} ({self.current_stock}{self.unit})"

    @property
    def is_low_stock(self):
        return self.current_stock <= self.reorder_threshold


class RecipeMap(models.Model):
    """How much of an Ingredient is consumed to make ONE unit of a MenuItem."""

    menu_item = models.ForeignKey(MenuItem, related_name='recipe_lines', on_delete=models.CASCADE)
    ingredient = models.ForeignKey(Ingredient, related_name='used_in', on_delete=models.PROTECT)
    quantity_required = models.DecimalField(
        max_digits=10, decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))],
        help_text="How much of this ingredient (in the ingredient's unit) one unit of the menu item consumes.",
    )

    class Meta:
        unique_together = ['menu_item', 'ingredient']
        ordering = ['menu_item__name', 'ingredient__name']

    def __str__(self):
        return f"{self.menu_item.name} needs {self.quantity_required}{self.ingredient.unit} {self.ingredient.name}"


class DemandForecast(models.Model):
    """A predicted quantity for one menu item on one future date."""

    shop = models.ForeignKey(Shop, related_name='forecasts', on_delete=models.CASCADE)
    menu_item = models.ForeignKey(MenuItem, related_name='forecasts', on_delete=models.CASCADE)
    forecast_date = models.DateField(help_text="The date this prediction is FOR.")
    predicted_quantity = models.DecimalField(max_digits=8, decimal_places=2)
    actual_quantity = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text="Filled in after forecast_date passes — actual units sold. Used by the Phase 5 anomaly agent.",
    )
    model_version = models.CharField(max_length=50, blank=True, help_text="Tag for which trained model produced this, e.g. a timestamp or git hash.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-forecast_date', 'menu_item__name']
        unique_together = ['menu_item', 'forecast_date']

    def __str__(self):
        return f"{self.menu_item.name} on {self.forecast_date}: predicted {self.predicted_quantity}"


class AgentLog(models.Model):
    """
    A record of one decision made by the reorder agent for one ingredient,
    on one run. This is the 'explainability' trail — every decision the
    agent makes gets logged with its reasoning, not just its final action.
    """

    class Decision(models.TextChoices):
        SUFFICIENT = 'sufficient', 'Sufficient stock — no action needed'
        LOW_STOCK = 'low_stock', 'Low stock — reorder message drafted'
        CRITICAL = 'critical', 'Critical — reorder message sent immediately'

    class ActionTaken(models.TextChoices):
        NONE = 'none', 'No action'
        LOGGED_ONLY = 'logged_only', 'Logged only'
        MESSAGE_DRAFTED = 'message_drafted', 'Message drafted (not sent)'
        MESSAGE_SENT = 'message_sent', 'Message sent to supplier'

    class Channel(models.TextChoices):
        NONE = 'none', 'None'
        WHATSAPP = 'whatsapp', 'WhatsApp'
        EMAIL = 'email', 'Email'

    shop = models.ForeignKey(Shop, related_name='agent_logs', on_delete=models.CASCADE)
    ingredient = models.ForeignKey('Ingredient', related_name='agent_logs', on_delete=models.CASCADE)
    run_date = models.DateField(help_text="The date this agent run was for (usually 'today', deciding for tomorrow's demand).")
    decision = models.CharField(max_length=20, choices=Decision.choices)
    action_taken = models.CharField(max_length=20, choices=ActionTaken.choices, default=ActionTaken.NONE)
    message_channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.NONE, help_text="Which channel the message was (or would be) sent through.")

    current_stock = models.DecimalField(max_digits=10, decimal_places=2)
    predicted_demand = models.DecimalField(max_digits=10, decimal_places=2, help_text="Total forecasted consumption of this ingredient for the forecast date.")
    projected_stock_after_demand = models.DecimalField(max_digits=10, decimal_places=2)
    suggested_order_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    reasoning = models.TextField(help_text="Plain-English explanation of why the agent decided what it decided.")
    message_draft = models.TextField(blank=True, help_text="The supplier reorder message, if one was drafted/sent.")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.ingredient.name} — {self.get_decision_display()} ({self.run_date})"


class DemandAnomaly(models.Model):
    """
    One day's forecast-vs-actual comparison for one menu item, classified as
    normal, over-forecast (wastage risk — we stocked more than we sold), or
    under-forecast (lost-sales risk — we sold more than we stocked for).
    """

    class Flag(models.TextChoices):
        NORMAL = 'normal', 'Normal — within expected variance'
        OVER_FORECAST = 'over_forecast', 'Over-forecast — wastage risk'
        UNDER_FORECAST = 'under_forecast', 'Under-forecast — lost sales risk'

    shop = models.ForeignKey(Shop, related_name='anomalies', on_delete=models.CASCADE)
    menu_item = models.ForeignKey(MenuItem, related_name='anomalies', on_delete=models.CASCADE)
    forecast_date = models.DateField()
    predicted_quantity = models.DecimalField(max_digits=8, decimal_places=2)
    actual_quantity = models.DecimalField(max_digits=8, decimal_places=2)
    variance = models.DecimalField(max_digits=8, decimal_places=2, help_text="actual - predicted")
    variance_pct = models.DecimalField(max_digits=6, decimal_places=2, help_text="variance as a % of predicted")
    flag = models.CharField(max_length=20, choices=Flag.choices, default=Flag.NORMAL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-forecast_date', 'menu_item__name']
        unique_together = ['menu_item', 'forecast_date']

    def __str__(self):
        return f"{self.menu_item.name} on {self.forecast_date}: {self.get_flag_display()} ({self.variance_pct}%)"


class WeeklySummaryReport(models.Model):
    """A plain-English weekly report generated by the anomaly agent — the interview-demo artifact."""

    shop = models.ForeignKey(Shop, related_name='weekly_summaries', on_delete=models.CASCADE)
    week_start = models.DateField()
    week_end = models.DateField()
    summary_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-week_start']

    def __str__(self):
        return f"Weekly summary {self.week_start} to {self.week_end}"