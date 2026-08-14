from django.contrib import admin

from .models import (
    AgentLog,
    Bill,
    DemandAnomaly,
    DemandForecast,
    Ingredient,
    Membership,
    MenuItem,
    Order,
    OrderItem,
    RecipeMap,
    Shop,
    WeeklySummaryReport,
)


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'slug']


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ['user', 'shop', 'role', 'created_at']
    list_filter = ['role', 'shop']


class RecipeMapInline(admin.TabularInline):
    model = RecipeMap
    extra = 1


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'price', 'cost_price', 'supports_fried_option', 'supports_cheese_option', 'is_active']
    list_filter = ['category', 'is_active', 'supports_fried_option', 'supports_cheese_option']
    search_fields = ['name']
    inlines = [RecipeMapInline]


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 1


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'status', 'table_or_token', 'subtotal', 'created_at']
    list_filter = ['status', 'created_at']
    inlines = [OrderItemInline]


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = ['id', 'order', 'subtotal', 'tax_amount', 'total', 'payment_method', 'created_at']
    list_filter = ['created_at', 'payment_method']
    readonly_fields = ['order', 'subtotal', 'tax_rate', 'tax_amount', 'total', 'payment_method', 'created_at']


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ['name', 'unit', 'current_stock', 'reorder_threshold', 'is_low_stock', 'supplier_contact', 'supplier_whatsapp']
    list_filter = ['unit']
    search_fields = ['name']

    def is_low_stock(self, obj):
        return obj.is_low_stock
    is_low_stock.boolean = True


@admin.register(RecipeMap)
class RecipeMapAdmin(admin.ModelAdmin):
    list_display = ['menu_item', 'ingredient', 'quantity_required']
    list_filter = ['menu_item', 'ingredient']


@admin.register(DemandForecast)
class DemandForecastAdmin(admin.ModelAdmin):
    list_display = ['menu_item', 'forecast_date', 'predicted_quantity', 'actual_quantity', 'model_version']
    list_filter = ['forecast_date', 'model_version']


@admin.register(AgentLog)
class AgentLogAdmin(admin.ModelAdmin):
    list_display = ['ingredient', 'run_date', 'decision', 'action_taken', 'message_channel', 'current_stock', 'predicted_demand', 'suggested_order_quantity']
    list_filter = ['decision', 'action_taken', 'message_channel', 'run_date']
    readonly_fields = [f.name for f in AgentLog._meta.fields]


@admin.register(DemandAnomaly)
class DemandAnomalyAdmin(admin.ModelAdmin):
    list_display = ['menu_item', 'forecast_date', 'predicted_quantity', 'actual_quantity', 'variance_pct', 'flag']
    list_filter = ['flag', 'forecast_date']


@admin.register(WeeklySummaryReport)
class WeeklySummaryReportAdmin(admin.ModelAdmin):
    list_display = ['week_start', 'week_end', 'created_at']
    readonly_fields = ['week_start', 'week_end', 'summary_text', 'created_at']
