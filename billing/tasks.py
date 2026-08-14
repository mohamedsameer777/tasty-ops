from datetime import date, timedelta

from celery import shared_task

from .agents import run_reorder_agent
from .anomaly_agent import generate_weekly_summary, run_anomaly_agent
from .forecasting import run_forecast_for_all_items
from .models import Shop


@shared_task
def run_nightly_forecast():
    """Forecasts tomorrow's demand for every active menu item, for every active shop. Scheduled to run each evening."""
    tomorrow = date.today() + timedelta(days=1)
    results = {}
    for shop in Shop.objects.filter(is_active=True):
        summary = run_forecast_for_all_items(shop, tomorrow)
        results[shop.slug] = len(summary)
    return {'forecast_date': tomorrow.isoformat(), 'items_forecast_by_shop': results}


@shared_task
def run_nightly_reorder_agent():
    """
    Runs the reorder decision agent against tomorrow's forecast, for every
    active shop. Scheduled to run shortly after run_nightly_forecast so
    predictions are fresh.
    """
    tomorrow = date.today() + timedelta(days=1)
    results = {}
    for shop in Shop.objects.filter(is_active=True):
        logs = run_reorder_agent(shop, tomorrow)
        results[shop.slug] = {
            'decisions': len(logs),
            'critical': sum(1 for log in logs if log.decision == 'critical'),
            'low_stock': sum(1 for log in logs if log.decision == 'low_stock'),
        }
    return {'forecast_date': tomorrow.isoformat(), 'by_shop': results}


@shared_task
def run_nightly_anomaly_check():
    """Backfills actuals for past forecasts and flags over/under-forecast days, for every active shop. Run once daily, after closing."""
    results = {}
    for shop in Shop.objects.filter(is_active=True):
        results[shop.slug] = run_anomaly_agent(shop)
    return results


@shared_task
def run_weekly_summary_report():
    """Generates the plain-English weekly forecast-accuracy report for every active shop. Scheduled weekly."""
    results = {}
    for shop in Shop.objects.filter(is_active=True):
        report = generate_weekly_summary(shop)
        results[shop.slug] = {'week_start': report.week_start.isoformat(), 'week_end': report.week_end.isoformat()}
    return results
