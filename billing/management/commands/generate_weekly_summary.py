from datetime import date, timedelta

from django.core.management.base import BaseCommand

from billing.anomaly_agent import generate_weekly_summary

from ._shop_utils import add_shop_argument, resolve_shop


class Command(BaseCommand):
    help = "Generates a plain-English weekly forecast-accuracy summary report for one shop."

    def add_arguments(self, parser):
        add_shop_argument(parser)
        parser.add_argument(
            '--week-start', type=str, default=None,
            help="Start of the week as YYYY-MM-DD. Defaults to 7 days ago.",
        )

    def handle(self, *args, **options):
        shop = resolve_shop(options)
        week_start = None
        if options['week_start']:
            week_start = date.fromisoformat(options['week_start'])

        report = generate_weekly_summary(shop, week_start)
        self.stdout.write(self.style.SUCCESS(f"Report for {shop.name}, {report.week_start} to {report.week_end}:\n"))
        self.stdout.write(report.summary_text)
