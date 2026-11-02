import json
import logging

from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.templatetags.static import static
from django.urls import reverse_lazy
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import CreateView, TemplateView
from django.utils.decorators import method_decorator

from .forms import ShopSignupForm


def normalize_phone(raw):
    """
    '98765 43210' / '+91 98765-43210' / '09876543210' -> '919876543210'.
    Returns '' for an empty value (clears the number) and None when it
    cannot be a real phone number. Digits only, country code included,
    because that is the form wa.me links need.
    """
    raw = (raw or '').strip()
    digits = ''.join(ch for ch in raw if ch.isdigit())
    if not digits:
        return '' if not raw else None    # empty -> clear the number; letters only -> invalid
    if len(digits) == 11 and digits.startswith('0'):
        digits = digits[1:]
    if len(digits) == 10:
        digits = '91' + digits          # default country code: India
    if not 11 <= len(digits) <= 15:
        return None
    return digits


class SignupView(CreateView):
    """
    Self-serve shop signup — creates a new Shop + owner User + Membership
    (see ShopSignupForm) and logs the new owner straight into their empty
    dashboard. Already-authenticated visitors are bounced to the dashboard
    instead of being allowed to create a second shop from this page.
    """
    form_class = ShopSignupForm
    template_name = 'registration/signup.html'
    success_url = reverse_lazy('dashboard')

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('dashboard')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        return response


class DashboardView(LoginRequiredMixin, TemplateView):
    """
    The dashboard — a single page that pulls live data from the API via
    JavaScript fetch() calls. No separate frontend build step needed;
    Django serves this directly.
    """
    template_name = 'billing/dashboard.html'

    def get_context_data(self, **kwargs):
        from .tenancy import get_shop_for_user
        context = super().get_context_data(**kwargs)
        context['shop'] = get_shop_for_user(self.request.user)
        return context


class HistoryView(LoginRequiredMixin, TemplateView):
    """
    Payment-app-style transaction history — yesterday/today totals, a
    day-by-day list going back 30 days, and per-day bill detail with full
    item breakdowns. Pulls data from /api/bills/history/.
    """
    template_name = 'billing/history.html'

    def get_context_data(self, **kwargs):
        from .tenancy import get_shop_for_user
        context = super().get_context_data(**kwargs)
        context['shop'] = get_shop_for_user(self.request.user)
        return context


class AnalyticsView(LoginRequiredMixin, TemplateView):
    """
    Spending-insights-style analytics — sales trend, best sellers,
    category breakdown, payment split, and peak hours. Pulls data from
    /api/bills/analytics/.
    """
    template_name = 'billing/analytics.html'

    def get_context_data(self, **kwargs):
        from .tenancy import get_shop_for_user
        context = super().get_context_data(**kwargs)
        context['shop'] = get_shop_for_user(self.request.user)
        return context


class OrderEntryView(LoginRequiredMixin, TemplateView):
    """The billing / order-entry page — punch in orders and generate bills from the browser."""
    template_name = 'billing/order_entry.html'

    def get_context_data(self, **kwargs):
        from .tenancy import get_shop_for_user
        context = super().get_context_data(**kwargs)
        context['shop'] = get_shop_for_user(self.request.user)
        return context


class ShopSettingsView(LoginRequiredMixin, View):
    """
    POST /shop-settings/  — update the logged-in owner's shop logo and/or
    location. Accepts multipart form data:
      - logo: an image file (optional)
      - latitude, longitude: decimal strings from navigator.geolocation (optional)
      - address: human-readable address string (optional, e.g. from reverse geocoding)
      - contact_phone: the owner's WhatsApp number - summaries are sent here (optional; send empty to clear)
    Returns the updated shop as JSON.
    """
    def post(self, request):
        import logging
        from decimal import Decimal, InvalidOperation
        from .tenancy import get_shop_for_user

        logger = logging.getLogger(__name__)
        shop = get_shop_for_user(request.user)
        if shop is None:
            return JsonResponse({'detail': 'No shop found for this account.'}, status=400)

        # Validate the phone number FIRST so a bad number never half-saves the other settings.
        contact_phone = request.POST.get('contact_phone')
        if contact_phone is not None:
            cleaned_phone = normalize_phone(contact_phone)
            if cleaned_phone is None:
                return JsonResponse(
                    {'detail': 'That phone number does not look right. Use 10 digits (e.g. 9876543210), or include the country code (919876543210).'},
                    status=400,
                )

        try:
            if contact_phone is not None:
                shop.contact_phone = cleaned_phone

            if 'logo' in request.FILES:
                shop.logo = request.FILES['logo']

            latitude = request.POST.get('latitude')
            longitude = request.POST.get('longitude')
            if latitude and longitude:
                try:
                    # Round to 6 decimal places ourselves so a browser sending
                    # 15+ decimal digits can never overflow the DB column.
                    shop.latitude = Decimal(latitude).quantize(Decimal('0.000001'))
                    shop.longitude = Decimal(longitude).quantize(Decimal('0.000001'))
                except InvalidOperation:
                    logger.warning("Ignoring unparseable lat/lng: %r, %r", latitude, longitude)

            address = request.POST.get('address')
            if address is not None:
                shop.address = address[:255]

            upi_id = request.POST.get('upi_id')
            if upi_id is not None:
                shop.upi_id = upi_id.strip()

            google_review_url = request.POST.get('google_review_url')
            if google_review_url is not None:
                shop.google_review_url = google_review_url.strip()

            instagram_url = request.POST.get('instagram_url')
            if instagram_url is not None:
                shop.instagram_url = instagram_url.strip()

            youtube_url = request.POST.get('youtube_url')
            if youtube_url is not None:
                shop.youtube_url = youtube_url.strip()

            daily_revenue_target = request.POST.get('daily_revenue_target')
            if daily_revenue_target is not None:
                shop.daily_revenue_target = daily_revenue_target.strip() or None

            shop.save()
        except Exception:
            logger.exception("shop-settings save failed for shop id=%s", shop.id)
            return JsonResponse({'detail': 'Could not save shop settings. Check the server logs.'}, status=500)

        return JsonResponse({
            'name': shop.name,
            'logo_url': shop.logo.url if shop.logo else None,
            'latitude': str(shop.latitude) if shop.latitude is not None else None,
            'longitude': str(shop.longitude) if shop.longitude is not None else None,
            'address': shop.address,
            'upi_id': shop.upi_id,
            'contact_phone': shop.contact_phone,
            'google_review_url': shop.google_review_url,
            'instagram_url': shop.instagram_url,
            'youtube_url': shop.youtube_url,
            'daily_revenue_target': str(shop.daily_revenue_target) if shop.daily_revenue_target is not None else None,
        })


class RunPredictionsView(LoginRequiredMixin, View):
    """
    POST /run-predictions/
    "Run the predictions now" for the logged-in shop, without waiting for the
    nightly job: re-forecasts tomorrow's demand for every dish from the real
    sales history, then back-fills actual sales for past forecasts.

    Deliberately does NOT run the reorder agent - that one messages suppliers
    on WhatsApp when stock is critical, and that should only happen from the
    nightly job, not from a button press.
    """
    def post(self, request):
        from collections import Counter
        from datetime import timedelta

        from django.utils import timezone

        from .anomaly_agent import run_anomaly_agent
        from .forecasting import run_forecast_for_all_items
        from .tenancy import get_shop_for_user

        logger = logging.getLogger(__name__)
        shop = get_shop_for_user(request.user)
        if shop is None:
            return JsonResponse({'detail': 'No shop found for this account.'}, status=400)

        forecast_date = timezone.localdate() + timedelta(days=1)
        try:
            summary = run_forecast_for_all_items(shop, forecast_date)
        except Exception:
            logger.exception("Manual forecast failed for shop %s", shop.slug)
            return JsonResponse({'detail': 'Forecast failed. Check the server logs.'}, status=500)

        result = {
            'forecast_date': forecast_date.isoformat(),
            'items_forecast': len(summary),
            'models_used': dict(Counter(row['model_kind'] for row in summary)),
            'trading_days_of_data': max((row['trading_days_used'] for row in summary), default=0),
        }
        try:
            result['anomaly_check'] = run_anomaly_agent(shop)
        except Exception:
            logger.exception("Manual anomaly check failed for shop %s", shop.slug)
            result['anomaly_check'] = None
        return JsonResponse(result)


@method_decorator(csrf_exempt, name='dispatch')
class BootstrapAdminView(View):
    """
    GET /bootstrap-admin/?token=...&username=...&password=...
    Creates a Django superuser without needing Render's paid Shell tab —
    reuses DAILY_JOBS_SECRET as the token since it's already configured.
    Refuses if that username already exists, so it can't be used to
    reset/guess an existing account's password.
    """
    def get(self, request):
        from django.conf import settings
        expected = getattr(settings, 'DAILY_JOBS_SECRET', '')
        token = request.GET.get('token', '')
        if not expected or token != expected:
            return JsonResponse({'detail': 'Forbidden'}, status=403)

        username = request.GET.get('username', '').strip()
        password = request.GET.get('password', '')
        if not username or not password:
            return JsonResponse({'detail': 'username and password query params are required'}, status=400)

        from django.contrib.auth import get_user_model
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            return JsonResponse(
                {'detail': f'A user named "{username}" already exists — pick a different username.'},
                status=400,
            )

        User.objects.create_superuser(username=username, email='', password=password)
        return JsonResponse({'detail': f'Superuser "{username}" created. Log in at /admin/.'})


@method_decorator(csrf_exempt, name='dispatch')
class RunDailyJobsView(View):
    """
    GET /run-daily-jobs/?token=...
    Meant to be triggered once a day by a free external scheduler (e.g.
    cron-job.org) instead of a persistent Celery worker, since Render's
    free tier only offers web services, not background workers. Runs
    demand forecasting + the reorder agent + anomaly backfill for every
    shop, and the weekly summary report on Mondays.

    Protected by a shared-secret token (the DAILY_JOBS_SECRET env var)
    instead of a login, since the caller here is a machine, not a browser.
    """
    def get(self, request):
        logger = logging.getLogger(__name__)

        from django.conf import settings
        expected = getattr(settings, 'DAILY_JOBS_SECRET', '')
        token = request.GET.get('token', '')
        if not expected or token != expected:
            return JsonResponse({'detail': 'Forbidden'}, status=403)

        from datetime import date, timedelta

        from .agents import run_reorder_agent
        from .anomaly_agent import generate_weekly_summary, run_anomaly_agent
        from .forecasting import run_forecast_for_all_items
        from .models import Shop

        today = date.today()
        forecast_date = today + timedelta(days=1)
        is_monday = today.weekday() == 0

        results = []
        for shop in Shop.objects.filter(is_active=True):
            shop_result = {'shop': shop.slug}

            try:
                forecasts = run_forecast_for_all_items(shop, forecast_date)
                shop_result['forecasts'] = len(forecasts) if forecasts else 0
            except Exception as exc:
                logger.exception("Forecast failed for shop %s", shop.slug)
                shop_result['forecast_error'] = str(exc)

            try:
                logs = run_reorder_agent(shop, forecast_date)
                shop_result['reorder_decisions'] = len(logs) if logs else 0
            except Exception as exc:
                logger.exception("Reorder agent failed for shop %s", shop.slug)
                shop_result['reorder_error'] = str(exc)

            try:
                shop_result['anomaly_check'] = run_anomaly_agent(shop)
            except Exception as exc:
                logger.exception("Anomaly agent failed for shop %s", shop.slug)
                shop_result['anomaly_error'] = str(exc)

            if is_monday:
                try:
                    report = generate_weekly_summary(shop)
                    shop_result['weekly_summary'] = f"{report.week_start} to {report.week_end}"
                except Exception as exc:
                    logger.exception("Weekly summary failed for shop %s", shop.slug)
                    shop_result['weekly_summary_error'] = str(exc)

            results.append(shop_result)

        return JsonResponse({
            'date': today.isoformat(),
            'forecast_date': forecast_date.isoformat(),
            'ran_weekly_summary': is_monday,
            'shops': results,
        })


class ServiceWorkerView(View):
    """
    Serves the service worker from the SITE ROOT (/sw.js) rather than under
    /static/ — a service worker's default scope is the folder it's served
    from, so serving it from /static/billing/ would only ever be able to
    control pages under /static/. Serving it from / lets it control the
    whole app (billing, dashboard, etc.).
    """
    def get(self, request):
        import os
        sw_path = os.path.join(os.path.dirname(__file__), 'static', 'billing', 'sw.js')
        with open(sw_path, 'r') as f:
            content = f.read()
        return HttpResponse(content, content_type='application/javascript')