from datetime import date, timedelta

from django.core.management.base import BaseCommand

from billing.agents import run_reorder_agent

from ._shop_utils import add_shop_argument, resolve_shop


class Command(BaseCommand):
    help = "Runs the reorder decision agent for every ingredient (for one shop) and logs each decision to AgentLog."

    def add_arguments(self, parser):
        add_shop_argument(parser)
        parser.add_argument(
            '--date', type=str, default=None,
            help="Forecast date to decide against, as YYYY-MM-DD. Defaults to tomorrow.",
        )

    def handle(self, *args, **options):
        shop = resolve_shop(options)
        forecast_date = date.today() + timedelta(days=1)
        if options['date']:
            forecast_date = date.fromisoformat(options['date'])

        self.stdout.write(f"Running reorder agent for {shop.name} against forecast date {forecast_date.isoformat()}...")
        logs = run_reorder_agent(shop, forecast_date)

        if not logs:
            self.stdout.write(self.style.WARNING("No ingredients found."))
            return

        for log in logs:
            style = self.style.SUCCESS if log.decision == 'sufficient' else (
                self.style.WARNING if log.decision == 'low_stock' else self.style.ERROR
            )
            self.stdout.write(style(
                f"  {log.ingredient.name:20s} [{log.get_decision_display()}] "
                f"action={log.get_action_taken_display()}"
            ))
            self.stdout.write(f"      {log.reasoning}")

        self.stdout.write(self.style.SUCCESS(f"Logged {len(logs)} decision(s)."))
