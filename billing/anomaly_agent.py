"""
The anomaly / wastage watch agent (Phase 5).

Two jobs:
1. Once a forecast_date has passed, backfill DemandForecast.actual_quantity
   from real billing data, then classify the day as normal / over-forecast
   (wastage risk) / under-forecast (lost-sales risk).
2. Weekly, look across the accumulated anomalies for repeating patterns
   (e.g. "Tuesdays are consistently overstocked on X") and write a
   plain-English WeeklySummaryReport.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncDate

from .models import DemandAnomaly, DemandForecast, MenuItem, OrderItem, WeeklySummaryReport

# Variance beyond this % (in either direction) gets flagged as an anomaly
# rather than normal day-to-day noise.
ANOMALY_THRESHOLD_PCT = Decimal('20.00')

WEEKDAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def _actual_quantity_sold(menu_item: MenuItem, on_date: date) -> Decimal:
    row = (
        OrderItem.objects
        .filter(menu_item=menu_item, order__bill__isnull=False)
        .annotate(sale_date=TruncDate('order__bill__created_at'))
        .filter(sale_date=on_date)
        .aggregate(total=Sum('quantity'))
    )
    return Decimal(row['total'] or 0)


def backfill_actuals(shop, as_of: date | None = None) -> int:
    """Fills in actual_quantity for every past forecast (for ONE shop) that doesn't have it yet. Returns count updated."""
    if as_of is None:
        as_of = date.today()

    pending = DemandForecast.objects.filter(shop=shop, forecast_date__lt=as_of, actual_quantity__isnull=True)
    updated = 0
    for forecast in pending:
        actual = _actual_quantity_sold(forecast.menu_item, forecast.forecast_date)
        forecast.actual_quantity = actual
        forecast.save(update_fields=['actual_quantity'])
        updated += 1
    return updated


def detect_anomalies(shop, as_of: date | None = None) -> list[DemandAnomaly]:
    """
    Classifies every forecast for ONE shop that now has an actual_quantity
    but hasn't been classified yet (or re-classifies if actual_quantity changed).
    """
    if as_of is None:
        as_of = date.today()

    forecasts = DemandForecast.objects.filter(
        shop=shop, forecast_date__lt=as_of, actual_quantity__isnull=False,
    ).select_related('menu_item')

    results = []
    for forecast in forecasts:
        predicted = forecast.predicted_quantity
        actual = forecast.actual_quantity
        variance = actual - predicted

        if predicted > 0:
            variance_pct = (variance / predicted * 100).quantize(Decimal('0.01'))
        else:
            variance_pct = Decimal('0.00') if actual == 0 else Decimal('100.00')

        if variance_pct <= -ANOMALY_THRESHOLD_PCT:
            flag = DemandAnomaly.Flag.OVER_FORECAST  # predicted too much -> wastage risk
        elif variance_pct >= ANOMALY_THRESHOLD_PCT:
            flag = DemandAnomaly.Flag.UNDER_FORECAST  # predicted too little -> lost sales risk
        else:
            flag = DemandAnomaly.Flag.NORMAL

        anomaly, _ = DemandAnomaly.objects.update_or_create(
            menu_item=forecast.menu_item, forecast_date=forecast.forecast_date,
            defaults={
                'shop': shop,
                'predicted_quantity': predicted,
                'actual_quantity': actual,
                'variance': variance,
                'variance_pct': variance_pct,
                'flag': flag,
            },
        )
        results.append(anomaly)

    return results


def generate_weekly_summary(shop, week_start: date | None = None) -> WeeklySummaryReport:
    """
    Looks at the last 7 days of anomalies for ONE shop and writes a
    plain-English report, specifically calling out repeating same-weekday
    patterns (e.g. "Tuesdays are consistently overstocked on Chicken 65").
    """
    if week_start is None:
        week_start = date.today() - timedelta(days=7)
    week_end = week_start + timedelta(days=6)

    anomalies = DemandAnomaly.objects.filter(
        shop=shop, forecast_date__gte=week_start, forecast_date__lte=week_end,
    ).select_related('menu_item')

    if not anomalies.exists():
        summary_text = (
            f"No forecast/actual data available for {week_start} to {week_end} yet — "
            f"nothing to summarize this week."
        )
        return WeeklySummaryReport.objects.create(
            shop=shop, week_start=week_start, week_end=week_end, summary_text=summary_text,
        )

    total = anomalies.count()
    over = anomalies.filter(flag=DemandAnomaly.Flag.OVER_FORECAST).count()
    under = anomalies.filter(flag=DemandAnomaly.Flag.UNDER_FORECAST).count()
    normal = total - over - under

    lines = [
        f"Weekly forecast accuracy report: {week_start} to {week_end}",
        f"{total} item-days evaluated — {normal} normal, {over} over-forecast (wastage risk), "
        f"{under} under-forecast (lost sales risk).",
        "",
    ]

    # Look for same-weekday, same-item, same-direction anomalies — the
    # "Tuesdays are consistently overstocked on X" pattern from the spec.
    # This needs multiple weeks of history to say anything meaningful about
    # a specific weekday, so we look across ALL of this shop's anomaly
    # history, not just this week, for the weekday-pattern part of the report.
    all_anomalies = DemandAnomaly.objects.filter(shop=shop).exclude(flag=DemandAnomaly.Flag.NORMAL).select_related('menu_item')
    pattern_counts = defaultdict(lambda: defaultdict(int))  # {(item, weekday): {flag: count}}
    for a in all_anomalies:
        key = (a.menu_item.name, a.forecast_date.weekday())
        pattern_counts[key][a.flag] += 1

    pattern_lines = []
    for (item_name, weekday), flags in pattern_counts.items():
        for flag, count in flags.items():
            if count >= 2:  # seen at least twice on this weekday — worth calling out
                direction = "overstocked" if flag == DemandAnomaly.Flag.OVER_FORECAST else "understocked"
                pattern_lines.append(
                    f"- {WEEKDAY_NAMES[weekday]}s are consistently {direction} on {item_name} "
                    f"({count} occurrences) — consider adjusting the forecast or order quantity for that day."
                )

    if pattern_lines:
        lines.append("Recurring patterns spotted:")
        lines.extend(pattern_lines)
    else:
        lines.append("No recurring same-weekday patterns detected yet — needs more weeks of data to be confident.")

    summary_text = "\n".join(lines)

    return WeeklySummaryReport.objects.create(
        shop=shop, week_start=week_start, week_end=week_end, summary_text=summary_text,
    )


def run_anomaly_agent(shop, as_of: date | None = None) -> dict:
    """Convenience entry point: backfill actuals, then detect anomalies, for ONE shop. Meant to run daily."""
    updated = backfill_actuals(shop, as_of)
    anomalies = detect_anomalies(shop, as_of)
    return {
        'actuals_backfilled': updated,
        'anomalies_evaluated': len(anomalies),
        'over_forecast': sum(1 for a in anomalies if a.flag == DemandAnomaly.Flag.OVER_FORECAST),
        'under_forecast': sum(1 for a in anomalies if a.flag == DemandAnomaly.Flag.UNDER_FORECAST),
    }
