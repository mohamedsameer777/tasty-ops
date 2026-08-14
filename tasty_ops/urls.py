"""
URL configuration for tasty_ops project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from billing.dashboard_views import (
    DashboardView, OrderEntryView, ServiceWorkerView, ShopSettingsView, SignupView,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('billing.urls')),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('accounts/signup/', SignupView.as_view(), name='signup'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('billing/', OrderEntryView.as_view(), name='order-entry'),
    path('shop-settings/', ShopSettingsView.as_view(), name='shop-settings'),
    path('sw.js', ServiceWorkerView.as_view(), name='service-worker'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)