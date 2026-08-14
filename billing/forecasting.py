"""
Demand forecasting for Tasty Zone Smart Ops.

Pulls historical sales (Bill/OrderItem), joins with day-of-week/weekend flags
and weather (via Open-Meteo — free, no API key needed), and trains a small
per-menu-item regression model to predict tomorrow's expected quantity sold.

Weather source: Open-Meteo (https://open-meteo.com/), coordinates set to
Palavakkam Beach, Chennai. If the weather API is unreachable (no internet,
API down, etc.) we just proceed without weather features rather than fail —
day-of-week and rolling averages alone still give a usable forecast.
"""
import logging
from datetime import date, timedelta

import pandas as pd
import requests
from django.db.models import Sum
from django.db.models.functions import TruncDate

from .models import Bill, MenuItem, OrderItem

logger = logging.getLogger(__name__)

# Palavakkam Beach, Chennai
LATITUDE = 12.9698
LONGITUDE = 80.2565

MIN_ROWS_FOR_ML_MODEL = 14  # below this, fall back to a simple rolling average


def _fetch_weather(start_date: date, end_date: date) -> dict:
    """
    Returns {date: {'temp_max': .., 'temp_min': .., 'precipitation': ..}}.
    Uses the historical archive API for past dates and the forecast API for
    today/future dates (Open-Meteo splits these into two endpoints).
    Returns {} on any failure — callers must handle missing weather data.
    """
    today = date.today()
    results = {}

    daily_fields = "temperature_2m_max,temperature_2m_min,precipitation_sum"

    def _parse(payload):
        daily = payload.get('daily', {})
        dates = daily.get('time', [])
        tmax = daily.get('temperature_2m_max', [])
        tmin = daily.get('temperature_2m_min', [])
        precip = daily.get('precipitation_sum', [])
        for i, d in enumerate(dates):
            results[d] = {
                'temp_max': tmax[i] if i < len(tmax) else None,
                'temp_min': tmin[i] if i < len(tmin) else None,
                'precipitation': precip[i] if i < len(precip) else None,
            }

    try:
        if start_date < today:
            hist_end = min(end_date, today - timedelta(days=1))
            resp = requests.get(
                "https://archive-api.open-meteo.com/v1/archive",
                params={
                    'latitude': LATITUDE, 'longitude': LONGITUDE,
                    'start_date': start_date.isoformat(), 'end_date': hist_end.isoformat(),
                    'daily': daily_fields, 'timezone': 'Asia/Kolkata',
                },
                timeout=10,
            )
            resp.raise_for_status()
            _parse(resp.json())

        if end_date >= today:
            resp = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    'latitude': LATITUDE, 'longitude': LONGITUDE,
                    'start_date': max(start_date, today).isoformat(), 'end_date': end_date.isoformat(),
                    'daily': daily_fields, 'timezone': 'Asia/Kolkata',
                },
                timeout=10,
            )
            resp.raise_for_status()
            _parse(resp.json())

    except (requests.RequestException, ValueError) as exc:
        logger.warning("Weather fetch failed (%s) — continuing without weather features.", exc)
        return {}

    return results


def _daily_sales_dataframe(menu_item: MenuItem) -> pd.DataFrame:
    """One row per day this item was sold, with quantity sold that day."""
    rows = (
        OrderItem.objects
        .filter(menu_item=menu_item, order__bill__isnull=False)
        .annotate(sale_date=TruncDate('order__bill__created_at'))
        .values('sale_date')
        .annotate(quantity_sold=Sum('quantity'))
        .order_by('sale_date')
    )
    df = pd.DataFrame(list(rows))
    if df.empty:
        return df
    df['sale_date'] = pd.to_datetime(df['sale_date'])
    return df


def _add_calendar_and_weather_features(df: pd.DataFrame, weather: dict) -> pd.DataFrame:
    df = df.copy()
    df['day_of_week'] = df['sale_date'].dt.dayofweek  # 0=Monday
    df['is_weekend'] = df['day_of_week'].isin([5, 6]).astype(int)

    df['temp_max'] = df['sale_date'].dt.strftime('%Y-%m-%d').map(lambda d: (weather.get(d) or {}).get('temp_max'))
    df['precipitation'] = df['sale_date'].dt.strftime('%Y-%m-%d').map(lambda d: (weather.get(d) or {}).get('precipitation'))

    # If weather is missing for a date (API down, etc.), fill with the
    # column's own mean rather than dropping the row.
    for col in ['temp_max', 'precipitation']:
        if df[col].notna().any():
            df[col] = df[col].fillna(df[col].mean())
        else:
            df[col] = 0.0

    return df


def forecast_menu_item(menu_item: MenuItem, forecast_date: date) -> tuple[float, str]:
    """
    Returns (predicted_quantity, model_version_tag).
    Trains a fresh small XGBoost model on this item's history if there's
    enough data; otherwise falls back to a simple recent-average heuristic.
    """
    history = _daily_sales_dataframe(menu_item)

    if history.empty:
        return 0.0, 'no-history-fallback'

    if len(history) < MIN_ROWS_FOR_ML_MODEL:
        # Not enough history for a model yet — use the mean of whatever we have.
        avg = float(history['quantity_sold'].mean())
        return round(avg, 2), 'rolling-average-fallback'

    weather = _fetch_weather(history['sale_date'].min().date(), forecast_date)
    history = _add_calendar_and_weather_features(history, weather)

    from xgboost import XGBRegressor

    feature_cols = ['day_of_week', 'is_weekend', 'temp_max', 'precipitation']
    X = history[feature_cols]
    y = history['quantity_sold']

    model = XGBRegressor(n_estimators=100, max_depth=3, learning_rate=0.1, random_state=42)
    model.fit(X, y)

    target_row = pd.DataFrame([{
        'day_of_week': forecast_date.weekday(),
        'is_weekend': int(forecast_date.weekday() in (5, 6)),
        'temp_max': (weather.get(forecast_date.isoformat()) or {}).get('temp_max') or X['temp_max'].mean(),
        'precipitation': (weather.get(forecast_date.isoformat()) or {}).get('precipitation') or X['precipitation'].mean(),
    }])
    prediction = float(model.predict(target_row)[0])
    prediction = max(0.0, prediction)  # never predict negative demand

    version_tag = f"xgb-{date.today().isoformat()}"
    return round(prediction, 2), version_tag


def run_forecast_for_all_items(shop, forecast_date: date | None = None) -> list[dict]:
    """
    Forecasts every active menu item for ONE shop on the given date
    (default: tomorrow) and upserts a DemandForecast row for each.
    Returns a summary list.
    """
    from .models import DemandForecast

    if forecast_date is None:
        forecast_date = date.today() + timedelta(days=1)

    summary = []
    for menu_item in MenuItem.objects.filter(shop=shop, is_active=True):
        predicted_quantity, version_tag = forecast_menu_item(menu_item, forecast_date)
        DemandForecast.objects.update_or_create(
            menu_item=menu_item, forecast_date=forecast_date,
            defaults={'shop': shop, 'predicted_quantity': predicted_quantity, 'model_version': version_tag},
        )
        summary.append({
            'menu_item': menu_item.name,
            'forecast_date': forecast_date.isoformat(),
            'predicted_quantity': predicted_quantity,
            'model_version': version_tag,
        })
    return summary
