from datetime import date, timedelta

from django.core.management.base import BaseCommand

from billing.forecasting import run_forecast_for_all_items

from ._shop_utils import add_shop_argument, resolve_shop


class Command(BaseCommand):
    help = "Runs demand forecasting for every active menu item (for one shop) and stores predictions in DemandForecast."

    def add_arguments(self, parser):
        add_shop_argument(parser)
        parser.add_argument(
            '--date', type=str, default=None,
            help="Forecast date as YYYY-MM-DD. Defaults to tomorrow.",
        )

    def handle(self, *args, **options):
        shop = resolve_shop(options)
        forecast_date = date.today() + timedelta(days=1)
        if options['date']:
            forecast_date = date.fromisoformat(options['date'])

        self.stdout.write(f"Running forecast for {shop.name} on {forecast_date.isoformat()}...")
        summary = run_forecast_for_all_items(shop, forecast_date)

        if not summary:
            self.stdout.write(self.style.WARNING("No active menu items to forecast."))
            return

        for row in summary:
            self.stdout.write(
                f"  {row['menu_item']:30s} predicted={row['predicted_quantity']:>6} "
                f"(model: {row['model_version']})"
            )
        self.stdout.write(self.style.SUCCESS(f"Stored {len(summary)} forecast(s) for {forecast_date.isoformat()}."))
