from django.core.management.base import BaseCommand

from billing.anomaly_agent import run_anomaly_agent

from ._shop_utils import add_shop_argument, resolve_shop


class Command(BaseCommand):
    help = "Backfills actuals for past forecasts (for one shop) and classifies them as normal/over-forecast/under-forecast."

    def add_arguments(self, parser):
        add_shop_argument(parser)

    def handle(self, *args, **options):
        shop = resolve_shop(options)
        result = run_anomaly_agent(shop)
        self.stdout.write(f"Backfilled actuals for {result['actuals_backfilled']} forecast(s) — {shop.name}.")
        self.stdout.write(
            f"Evaluated {result['anomalies_evaluated']} item-day(s): "
            f"{result['over_forecast']} over-forecast, {result['under_forecast']} under-forecast."
        )
        self.stdout.write(self.style.SUCCESS("Anomaly check complete."))
