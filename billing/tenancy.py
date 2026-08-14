"""
Multi-tenant scoping helpers.

Every shop owner's data must be invisible to every other shop owner. Rather
than trust each view to remember to filter by shop, every tenant-scoped
viewset mixes in TenantScopedMixin, which:
  1. Resolves the current user's Shop via their Membership (raises 403 if
     the account isn't linked to a shop — e.g. it was never set up, or the
     shop was deactivated).
  2. Filters get_queryset() to that shop automatically.
  3. Stamps `shop` onto anything created through the viewset automatically.

A user can only ever see/act on rows already filtered to their own shop —
even a raw "give me object id=17" lookup 404s instead of leaking another
shop's row, because get_object() is built on top of the scoped queryset.
"""
from rest_framework.exceptions import PermissionDenied

from .models import Membership


def get_shop_for_user(user):
    """Returns the Shop for this user, or None if they're not linked to one."""
    if not user or not user.is_authenticated:
        return None
    try:
        membership = user.membership
    except Membership.DoesNotExist:
        return None
    if not membership.shop.is_active:
        return None
    return membership.shop


class TenantScopedMixin:
    """
    Mix into a ModelViewSet/ReadOnlyModelViewSet.

    shop_lookup: the queryset filter path to the shop, e.g. 'shop' for a
    model with a direct shop FK, or 'order__shop' / 'menu_item__shop' for
    models that only reach Shop through a relation.
    """
    shop_lookup = 'shop'

    def get_current_shop(self):
        shop = get_shop_for_user(self.request.user)
        if shop is None:
            raise PermissionDenied("Your account isn't linked to an active shop.")
        return shop

    def get_queryset(self):
        qs = super().get_queryset()
        shop = self.get_current_shop()
        return qs.filter(**{self.shop_lookup: shop})

    def perform_create(self, serializer):
        # Only stamp `shop` directly onto models that actually have that
        # field (shop_lookup == 'shop'). Models reached via a relation
        # (Bill via order, RecipeMap via menu_item) get their tenant
        # boundary from their parent object instead — see those viewsets.
        if self.shop_lookup == 'shop':
            serializer.save(shop=self.get_current_shop())
        else:
            serializer.save()
