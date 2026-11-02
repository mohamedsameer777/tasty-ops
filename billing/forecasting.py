"""
Demand forecasting for Tasty Zone Smart Ops.

Learns from the shop's REAL sales history (Bill / OrderItem) and predicts how
many of each dish will sell on a given day (default: tomorrow).

How a dish is forecast, depending on how much real history it has:
  * no sales ever ................ 0
  * under 14 trading days ........ recency-weighted average, adjusted for
                                   the same weekday when there are 2+ of them
  * 14+ trading days ............. XGBoost (day of week, weekend, weather)
                                   blended with that weighted average, so a
                                   small data set can't make the model swing wildly

What counts as a trading day: any day the shop made at least one bill. On a
trading day a dish that did not sell counts as ZERO sold. Leaving those days
out would make slow dishes look busier than they are.

Today is left out of the training data until 9 pm (it is still incomplete), and
demo rows from `generate_synthetic_sales` are ignored unless asked for.

Weather source: Open-Meteo (free, no API key), at the shop's own location
(set in Shop Settings), falling back to Palavakkam Beach, Chennai. It is
fetched ONCE per run, not once per dish. If it is unreachable the forecast
simply carries on without weather features.
"""
import logging
from datetime import date, timedelta

import pandas as pd
import requests
from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from .models import Bill, MenuItem
from .sales_summary import SYNTHETIC_ORDER_TAG, real_order_items

logger = logging.getLogger(__name__)

# Fallback location: Palavakkam Beach, Chennai
LATITUDE = 12.9698
LONGITUDE = 80.2565

MIN_ROWS_FOR_ML_MODEL = 14      # trading days an item needs before XGBoost is used
ML_BLEND = 0.6                  # share of the final number that comes from XGBoost
RECENCY_HALF_LIFE_DAYS = 14     # a day's sales count half as much 14 days later
TODAY_COUNTS_AFTER_HOUR = 21    # before this hour, today is "still open" and not trained on


# --------------------------------------------------------------------------
# Weather
# --------------------------------------------------------------------------

def _fetch_weather(start_date: date, end_date: date, latitude=LATITUDE, longitude=LONGITUDE) -> dict:
    """
    Returns {'YYYY-MM-DD': {'temp_max': .., 'temp_min': .., 'precipitation': ..}}.
    Uses the historical archive API for past dates and the forecast API for
    today/future dates (Open-Meteo splits these into two endpoints).
    Returns {} on any failure - callers must handle missing weather data.
    """
    today = timezone.localdate()
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
                    'latitude': latitude, 'longitude': longitude,
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
                    'latitude': latitude, 'longitude': longitude,
                    'start_date': max(start_date, today).isoformat(), 'end_date': end_date.isoformat(),
                    'daily': daily_fields, 'timezone': 'Asia/Kolkata',
                },
                timeout=10,
            )
            resp.raise_for_status()
            _parse(resp.json())

    except (requests.RequestException, ValueError) as exc:
        logger.warning("Weather fetch failed (%s) - continuing without weather features.", exc)
        return {}

    return results


def _shop_coordinates(shop):
    if shop is not None and shop.latitude is not None and shop.longitude is not None:
        return float(shop.latitude), float(shop.longitude)
    return LATITUDE, LONGITUDE


# --------------------------------------------------------------------------
# Sales history
# --------------------------------------------------------------------------

def _last_complete_day() -> date:
    """The latest day whose sales are complete enough to learn from."""
    now = timezone.localtime()
    return now.date() if now.hour >= TODAY_COUNTS_AFTER_HOUR else now.date() - timedelta(days=1)


def _trading_days(shop, last_day: date, include_synthetic: bool) -> list:
    """Every date up to last_day on which the shop made at least one bill, oldest first."""
    qs = Bill.objects.filter(order__shop=shop)
    if not include_synthetic:
        qs = qs.exclude(order__table_or_token=SYNTHETIC_ORDER_TAG)
    return list(
        qs.annotate(day=TruncDate('created_at'))
        .filter(day__lte=last_day)
        .order_by('day')                 # also clears Bill's default ordering so distinct() works
        .values_list('day', flat=True)
        .distinct()
    )


def _sales_by_item(shop, last_day: date, include_synthetic: bool, menu_item=None) -> dict:
    """{menu_item_id: {date: units sold that day}} for real sales up to last_day."""
    qs = real_order_items(shop, include_synthetic)
    if menu_item is not None:
        qs = qs.filter(menu_item=menu_item)
    rows = (
        qs.annotate(sale_date=TruncDate('order__bill__created_at'))
        .filter(sale_date__lte=last_day)
        .values('menu_item_id', 'sale_date')
        .annotate(units=Sum('quantity'))
        .order_by()
    )
    sales = {}
    for row in rows:
        sales.setdefault(row['menu_item_id'], {})[row['sale_date']] = row['units'] or 0
    return sales


def _history_dataframe(menu_item: MenuItem, item_sales: dict, trading_days: list) -> pd.DataFrame:
    """
    One row per TRADING day since this dish first existed, with units sold
    that day - zero on days it did not sell.
    """
    if not item_sales:
        return pd.DataFrame(columns=['sale_date', 'quantity_sold'])

    created_day = timezone.localtime(menu_item.created_at).date()
    start = min(min(item_sales), created_day)
    days = [d for d in trading_days if d >= start]
    if not days:
        return pd.DataFrame(columns=['sale_date', 'quantity_sold'])

    return pd.DataFrame({
        'sale_date': pd.to_datetime(days),
        'quantity_sold': [float(item_sales.get(d, 0)) for d in days],
    })


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------

def _recency_weights(history: pd.DataFrame) -> pd.Series:
    age_days = (history['sale_date'].max() - history['sale_date']).dt.days
    return 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)


def _weighted_baseline(history: pd.DataFrame, forecast_date: date) -> tuple[float, str]:
    """Recency-weighted average; blended with the same-weekday average when there are 2+ of that weekday."""
    weights = _recency_weights(history)
    overall = float((history['quantity_sold'] * weights).sum() / weights.sum())

    same_weekday = history[history['sale_date'].dt.dayofweek == forecast_date.weekday()]
    if len(same_weekday) >= 2:
        w = weights.loc[same_weekday.index]
        weekday_avg = float((same_weekday['quantity_sold'] * w).sum() / w.sum())
        return 0.5 * overall + 0.5 * weekday_avg, 'weekday-weighted-average'
    return overall, 'weighted-average'


def _add_calendar_and_weather_features(df: pd.DataFrame, weather: dict) -> pd.DataFrame:
    df = df.copy()
    df['day_of_week'] = df['sale_date'].dt.dayofweek  # 0=Monday
    df['is_weekend'] = df['day_of_week'].isin([5, 6]).astype(int)

    keys = df['sale_date'].dt.strftime('%Y-%m-%d')
    df['temp_max'] = keys.map(lambda d: (weather.get(d) or {}).get('temp_max'))
    df['precipitation'] = keys.map(lambda d: (weather.get(d) or {}).get('precipitation'))

    # If weather is missing for a date (API down, etc.), fill with the
    # column's own mean rather than dropping the row.
    for col in ['temp_max', 'precipitation']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        if df[col].notna().any():
            df[col] = df[col].fillna(df[col].mean())
        else:
            df[col] = 0.0
    return df


def _forecast_from_history(history: pd.DataFrame, forecast_date: date, weather: dict) -> tuple[float, str]:
    """Returns (predicted_quantity, model_kind)."""
    if history.empty or history['quantity_sold'].sum() == 0:
        return 0.0, 'no-history-fallback'

    baseline, kind = _weighted_baseline(history, forecast_date)

    if len(history) < MIN_ROWS_FOR_ML_MODEL:
        return round(max(0.0, baseline), 2), kind

    from xgboost import XGBRegressor

    history = _add_calendar_and_weather_features(history, weather)
    feature_cols = ['day_of_week', 'is_weekend', 'temp_max', 'precipitation']
    X = history[feature_cols]
    y = history['quantity_sold']

    model = XGBRegressor(n_estimators=100, max_depth=3, learning_rate=0.1, random_state=42)
    model.fit(X, y, sample_weight=_recency_weights(history))

    target = weather.get(forecast_date.isoformat()) or {}
    temp = target.get('temp_max')
    rain = target.get('precipitation')
    target_row = pd.DataFrame([{
        'day_of_week': forecast_date.weekday(),
        'is_weekend': int(forecast_date.weekday() in (5, 6)),
        # `is None`, not `or`: 0.0 mm of rain is a real reading, not "missing".
        'temp_max': float(temp) if temp is not None else float(X['temp_max'].mean()),
        'precipitation': float(rain) if rain is not None else float(X['precipitation'].mean()),
    }])
    ml_prediction = float(model.predict(target_row)[0])

    prediction = ML_BLEND * ml_prediction + (1 - ML_BLEND) * baseline
    prediction = min(prediction, float(y.max()) * 1.5)   # never predict far beyond anything ever sold
    return round(max(0.0, prediction), 2), 'xgb-blend'


def _version_tag(kind: str) -> str:
    if kind == 'no-history-fallback':
        return kind
    return f"{kind}-{timezone.localdate().isoformat()}"


def forecast_menu_item(menu_item: MenuItem, forecast_date: date, weather: dict | None = None,
                       include_synthetic: bool = False) -> tuple[float, str]:
    """
    Returns (predicted_quantity, model_version_tag) for ONE dish.
    Pass `weather` (from _fetch_weather) to avoid a network call per dish.
    """
    shop = menu_item.shop
    last_day = _last_complete_day()
    trading_days = _trading_days(shop, last_day, include_synthetic)
    item_sales = _sales_by_item(shop, last_day, include_synthetic, menu_item).get(menu_item.id, {})
    history = _history_dataframe(menu_item, item_sales, trading_days)

    if weather is None:
        weather = {}
        if len(history) >= MIN_ROWS_FOR_ML_MODEL:
            lat, lon = _shop_coordinates(shop)
            weather = _fetch_weather(history['sale_date'].min().date(), forecast_date, lat, lon)

    prediction, kind = _forecast_from_history(history, forecast_date, weather)
    return prediction, _version_tag(kind)


def run_forecast_for_all_items(shop, forecast_date: date | None = None, include_synthetic: bool = False) -> list[dict]:
    """
    Forecasts every active menu item for ONE shop on the given date
    (default: tomorrow) from its real sales history, and upserts a
    DemandForecast row for each. Returns a summary list.
    """
    from .models import DemandForecast

    if forecast_date is None:
        forecast_date = timezone.localdate() + timedelta(days=1)

    last_day = _last_complete_day()
    trading_days = _trading_days(shop, last_day, include_synthetic)
    sales = _sales_by_item(shop, last_day, include_synthetic)
    items = list(MenuItem.objects.filter(shop=shop, is_active=True))

    # One weather request for the whole run - and only if some dish will use it.
    weather = {}
    if len(trading_days) >= MIN_ROWS_FOR_ML_MODEL:
        lat, lon = _shop_coordinates(shop)
        weather = _fetch_weather(trading_days[0], forecast_date, lat, lon)

    summary = []
    for menu_item in items:
        history = _history_dataframe(menu_item, sales.get(menu_item.id, {}), trading_days)
        predicted_quantity, kind = _forecast_from_history(history, forecast_date, weather)
        version_tag = _version_tag(kind)

        DemandForecast.objects.update_or_create(
            menu_item=menu_item, forecast_date=forecast_date,
            defaults={'shop': shop, 'predicted_quantity': predicted_quantity, 'model_version': version_tag},
        )
        summary.append({
            'menu_item': menu_item.name,
            'forecast_date': forecast_date.isoformat(),
            'predicted_quantity': predicted_quantity,
            'model_version': version_tag,
            'model_kind': kind,
            'trading_days_used': len(history),
        })
    return summary