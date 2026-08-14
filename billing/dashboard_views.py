import json

from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.templatetags.static import static
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, TemplateView

from .forms import ShopSignupForm


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
    Returns the updated shop as JSON.
    """
    def post(self, request):
        from .tenancy import get_shop_for_user
        shop = get_shop_for_user(request.user)
        if shop is None:
            return JsonResponse({'detail': 'No shop found for this account.'}, status=400)

        if 'logo' in request.FILES:
            shop.logo = request.FILES['logo']

        latitude = request.POST.get('latitude')
        longitude = request.POST.get('longitude')
        if latitude and longitude:
            shop.latitude = latitude
            shop.longitude = longitude

        address = request.POST.get('address')
        if address is not None:
            shop.address = address

        upi_id = request.POST.get('upi_id')
        if upi_id is not None:
            shop.upi_id = upi_id.strip()

        shop.save()

        return JsonResponse({
            'name': shop.name,
            'logo_url': shop.logo.url if shop.logo else None,
            'latitude': str(shop.latitude) if shop.latitude is not None else None,
            'longitude': str(shop.longitude) if shop.longitude is not None else None,
            'address': shop.address,
            'upi_id': shop.upi_id,
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