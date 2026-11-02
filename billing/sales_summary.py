"""
Dish-level sales summaries: "how many of each dish did we sell today / this
week / this month?", most-selling first.

Only REAL sales count. Rows created by the `generate_synthetic_sales` demo
command are tagged with table_or_token='synthetic' and are left out, so these
numbers - and the demand forecasts built from them - reflect what actually
happened at the stall.
"""
from datetime import timedelta

from django.db.models import F, Sum
from django.utils import timezone

from .models import OrderItem

# Same tag generate_synthetic_sales stamps on its fake orders.
SYNTHETIC_ORDER_TAG = 'synthetic'

PERIOD_CHOICES = ('today', 'yesterday', 'week', 'last_week', 'month', 'last_month', 'last_7', 'last_30')


def period_range(period, today=None):
    """
    Returns (start_date, end_date, label) - both dates inclusive, in the
    shop's local calendar. Weeks run Monday-Sunday, like the dashboard's
    Revenue Report. Raises ValueError for an unknown period.
    """
    today = today or timezone.localdate()

    if period == 'today':
        return today, today, 'Today'
    if period == 'yesterday':
        d = today - timedelta(days=1)
        return d, d, 'Yesterday'
    if period == 'week':
        return today - timedelta(days=today.weekday()), today, 'This Week'
    if period == 'last_week':
        this_monday = today - timedelta(days=today.weekday())
        return this_monday - timedelta(days=7), this_monday - timedelta(days=1), 'Last Week'
    if period == 'month':
        return today.replace(day=1), today, 'This Month'
    if period == 'last_month':
        last_day_prev = today.replace(day=1) - timedelta(days=1)
        return last_day_prev.replace(day=1), last_day_prev, 'Last Month'
    if period == 'last_7':
        return today - timedelta(days=6), today, 'Last 7 Days'
    if period == 'last_30':
        return today - timedelta(days=29), today, 'Last 30 Days'
    raise ValueError(f"Unknown period '{period}'. Use one of: {', '.join(PERIOD_CHOICES)}.")


def describe_range(start, end):
    """'30 Oct 2026' for one day, '26 Oct – 30 Oct 2026' for a span."""
    if start == end:
        return f"{start.day} {start.strftime('%b %Y')}"
    if start.year == end.year:
        return f"{start.day} {start.strftime('%b')} – {end.day} {end.strftime('%b %Y')}"
    return f"{start.day} {start.strftime('%b %Y')} – {end.day} {end.strftime('%b %Y')}"


def real_order_items(shop, include_synthetic=False):
    """Every sold OrderItem (its order has a bill) for ONE shop, minus demo data by default."""
    qs = OrderItem.objects.filter(order__shop=shop, order__bill__isnull=False)
    if not include_synthetic:
        qs = qs.exclude(order__table_or_token=SYNTHETIC_ORDER_TAG)
    return qs


def dish_sales(shop, start, end, include_synthetic=False):
    """
    Units sold and revenue per dish between two dates (inclusive), best
    seller first. Fried / cheese / parcel variants of a dish are combined
    into that one dish. Dishes with no sales in the range are not listed.
    """
    rows = (
        real_order_items(shop, include_synthetic)
        .filter(order__bill__created_at__date__gte=start, order__bill__created_at__date__lte=end)
        .values('menu_item_id', 'menu_item__name', 'menu_item__category')
        # NB: alias is "units", not "quantity" - an alias equal to a model
        # field name collides with F('quantity') inside the same query.
        .annotate(units=Sum('quantity'), revenue=Sum(F('unit_price') * F('quantity')))
        .order_by('-units', 'menu_item__name')
    )

    items = []
    for rank, row in enumerate(rows, start=1):
        items.append({
            'rank': rank,
            'menu_item_id': row['menu_item_id'],
            'name': row['menu_item__name'],
            'category': row['menu_item__category'],
            'quantity': row['units'] or 0,
            'revenue': str(row['revenue'] or 0),
        })

    total_units = sum(i['quantity'] for i in items)
    total_revenue = sum(float(i['revenue']) for i in items)
    days = (end - start).days + 1

    return {
        'start_date': start.isoformat(),
        'end_date': end.isoformat(),
        'range_text': describe_range(start, end),
        'days_in_period': days,
        'total_units': total_units,
        'total_revenue': f"{total_revenue:.2f}",
        'dish_count': len(items),
        'avg_units_per_day': round(total_units / days, 1) if days else 0,
        'top_seller': items[0] if items else None,
        'items': items,
    }


def summary_lines(items, limit=None):
    """['Chicken Momo (6 PCS): 12', ...] - dish and how many sold, nothing else."""
    shown = items[:limit] if limit else items
    return [f"{i['name']}: {i['quantity']}" for i in shown]