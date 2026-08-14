"""
Shared helper for the manually-run agent/data commands. Not a command
itself (no Command class), so Django's autodiscovery skips it.
"""
from django.core.management.base import CommandError


def add_shop_argument(parser):
    parser.add_argument(
        '--shop', type=str, default=None,
        help="Shop slug to operate on. Only optional if exactly one shop exists.",
    )


def resolve_shop(options):
    from billing.models import Shop

    slug = options.get('shop')
    if slug:
        try:
            return Shop.objects.get(slug=slug)
        except Shop.DoesNotExist:
            raise CommandError(f"No shop with slug '{slug}'.")

    shops = list(Shop.objects.all())
    if not shops:
        raise CommandError("No shops exist yet — sign up at /accounts/signup/ first.")
    if len(shops) == 1:
        return shops[0]

    available = ", ".join(s.slug for s in shops)
    raise CommandError(f"Multiple shops exist — pass --shop <slug>. Available: {available}")
