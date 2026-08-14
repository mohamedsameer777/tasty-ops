from rest_framework.routers import DefaultRouter

from .views import (
    AgentLogViewSet,
    BillViewSet,
    DemandAnomalyViewSet,
    DemandForecastViewSet,
    IngredientViewSet,
    MenuItemViewSet,
    OrderViewSet,
    RecipeMapViewSet,
    WeeklySummaryReportViewSet,
)

router = DefaultRouter()
router.register('menu-items', MenuItemViewSet, basename='menu-item')
router.register('orders', OrderViewSet, basename='order')
router.register('bills', BillViewSet, basename='bill')
router.register('ingredients', IngredientViewSet, basename='ingredient')
router.register('recipe-map', RecipeMapViewSet, basename='recipe-map')
router.register('forecasts', DemandForecastViewSet, basename='forecast')
router.register('agent-logs', AgentLogViewSet, basename='agent-log')
router.register('anomalies', DemandAnomalyViewSet, basename='anomaly')
router.register('weekly-summaries', WeeklySummaryReportViewSet, basename='weekly-summary')

urlpatterns = router.urls
