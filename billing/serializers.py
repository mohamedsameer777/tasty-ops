from decimal import Decimal

from rest_framework import serializers

from .models import (
    AgentLog,
    Bill,
    DemandAnomaly,
    DemandForecast,
    Ingredient,
    MenuItem,
    Order,
    OrderItem,
    RecipeMap,
    WeeklySummaryReport,
)


class MenuItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = MenuItem
        fields = ['id', 'name', 'category', 'price', 'cost_price', 'image', 'supports_fried_option', 'supports_cheese_option', 'is_active']


class OrderItemSerializer(serializers.ModelSerializer):
    menu_item_name = serializers.CharField(source='menu_item.name', read_only=True)
    display_name = serializers.CharField(read_only=True)
    line_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = [
            'id', 'menu_item', 'menu_item_name', 'display_name', 'quantity',
            'is_parcel', 'is_fried', 'has_extra_cheese', 'unit_price', 'line_total',
        ]
        read_only_fields = ['unit_price']


class OrderItemWriteSerializer(serializers.Serializer):
    """Used for the 'add items to order' endpoint — menu_item id + quantity + chosen modifiers."""
    menu_item = serializers.PrimaryKeyRelatedField(queryset=MenuItem.objects.filter(is_active=True))
    quantity = serializers.IntegerField(min_value=1)
    is_parcel = serializers.BooleanField(default=False)
    is_fried = serializers.BooleanField(default=False)
    has_extra_cheese = serializers.BooleanField(default=False)


class SetItemQuantitySerializer(serializers.Serializer):
    """Sets a line item to an EXACT quantity (not incremental). quantity=0 removes the line entirely.
    Modifiers identify WHICH line — e.g. fried vs steamed Chicken Momo are separate lines."""
    menu_item = serializers.PrimaryKeyRelatedField(queryset=MenuItem.objects.all())
    quantity = serializers.IntegerField(min_value=0)
    is_parcel = serializers.BooleanField(default=False)
    is_fried = serializers.BooleanField(default=False)
    has_extra_cheese = serializers.BooleanField(default=False)


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'daily_number', 'status', 'table_or_token', 'customer_name', 'customer_phone',
            'created_at', 'updated_at', 'items', 'subtotal',
        ]

    def get_subtotal(self, obj):
        return obj.subtotal


class BillSerializer(serializers.ModelSerializer):
    order = OrderSerializer(read_only=True)

    class Meta:
        model = Bill
        fields = ['id', 'daily_number', 'order', 'subtotal', 'tax_rate', 'tax_amount', 'total', 'payment_method', 'cash_amount', 'upi_amount', 'created_at']


class GenerateBillSerializer(serializers.Serializer):
    """tax_rate defaults to 0 (no tax) unless you explicitly pass one. payment_method is required.
    cash_amount/upi_amount are only used (and required) when payment_method is 'split'."""
    tax_rate = serializers.DecimalField(max_digits=4, decimal_places=2, required=False, default=Decimal('0.00'))
    payment_method = serializers.ChoiceField(choices=Bill.PaymentMethod.choices, default=Bill.PaymentMethod.CASH)
    cash_amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    upi_amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)


class IngredientSerializer(serializers.ModelSerializer):
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Ingredient
        fields = [
            'id', 'name', 'unit', 'current_stock', 'reorder_threshold',
            'supplier_contact', 'supplier_whatsapp', 'is_low_stock', 'created_at', 'updated_at',
        ]


class RecipeMapSerializer(serializers.ModelSerializer):
    menu_item_name = serializers.CharField(source='menu_item.name', read_only=True)
    ingredient_name = serializers.CharField(source='ingredient.name', read_only=True)
    ingredient_unit = serializers.CharField(source='ingredient.unit', read_only=True)

    class Meta:
        model = RecipeMap
        fields = [
            'id', 'menu_item', 'menu_item_name', 'ingredient', 'ingredient_name',
            'ingredient_unit', 'quantity_required',
        ]


class DemandForecastSerializer(serializers.ModelSerializer):
    menu_item_name = serializers.CharField(source='menu_item.name', read_only=True)

    class Meta:
        model = DemandForecast
        fields = [
            'id', 'menu_item', 'menu_item_name', 'forecast_date',
            'predicted_quantity', 'actual_quantity', 'model_version', 'created_at',
        ]


class AgentLogSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(source='ingredient.name', read_only=True)

    class Meta:
        model = AgentLog
        fields = [
            'id', 'ingredient', 'ingredient_name', 'run_date', 'decision', 'action_taken', 'message_channel',
            'current_stock', 'predicted_demand', 'projected_stock_after_demand',
            'suggested_order_quantity', 'reasoning', 'message_draft', 'created_at',
        ]


class DemandAnomalySerializer(serializers.ModelSerializer):
    menu_item_name = serializers.CharField(source='menu_item.name', read_only=True)

    class Meta:
        model = DemandAnomaly
        fields = [
            'id', 'menu_item', 'menu_item_name', 'forecast_date', 'predicted_quantity',
            'actual_quantity', 'variance', 'variance_pct', 'flag', 'created_at',
        ]


class WeeklySummaryReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = WeeklySummaryReport
        fields = ['id', 'week_start', 'week_end', 'summary_text', 'created_at']