from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import (
    AgentLog,
    Bill,
    DemandAnomaly,
    DemandForecast,
    Ingredient,
    MenuItem,
    Order,
    OrderItem,
    RecipeMap,
    WeeklySummaryReport,
)
from .serializers import (
    AgentLogSerializer,
    BillSerializer,
    DemandAnomalySerializer,
    DemandForecastSerializer,
    GenerateBillSerializer,
    IngredientSerializer,
    MenuItemSerializer,
    OrderItemWriteSerializer,
    OrderSerializer,
    RecipeMapSerializer,
    SetItemQuantitySerializer,
    WeeklySummaryReportSerializer,
)
from .tenancy import TenantScopedMixin


class MenuItemViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    """
    Full CRUD for the menu — scoped to the logged-in user's shop.
    GET    /api/menu-items/          list
    POST   /api/menu-items/          create
    GET    /api/menu-items/{id}/     retrieve
    PATCH  /api/menu-items/{id}/     partial update (e.g. change price)
    DELETE /api/menu-items/{id}/     delete
    """
    queryset = MenuItem.objects.all()
    serializer_class = MenuItemSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        active_only = self.request.query_params.get('active_only')
        if active_only == 'true':
            qs = qs.filter(is_active=True)
        return qs


class OrderViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    """
    GET    /api/orders/                 list orders (filter with ?status=open)
    POST   /api/orders/                 start a new order
    GET    /api/orders/{id}/            retrieve one order with its items
    POST   /api/orders/{id}/add_items/  add one or more items to an open order
    POST   /api/orders/{id}/generate_bill/  finalize the order into a Bill
    """
    queryset = Order.objects.prefetch_related('items__menu_item').all()
    serializer_class = OrderSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @action(detail=True, methods=['post'])
    def add_items(self, request, pk=None):
        order = self.get_object()
        if order.status != Order.Status.OPEN:
            return Response(
                {'detail': f"Cannot add items to an order with status '{order.status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Accept either a single item {"menu_item": 1, "quantity": 2}
        # or a list [{"menu_item": 1, "quantity": 2}, {"menu_item": 3, "quantity": 1}]
        payload = request.data if isinstance(request.data, list) else [request.data]
        serializer = OrderItemWriteSerializer(data=payload, many=True)
        # Scope the menu_item choices to THIS shop only — otherwise a
        # crafted request could add another shop's menu item id to an order.
        self._scope_menu_item_field(serializer)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            for entry in serializer.validated_data:
                menu_item = entry['menu_item']
                quantity = entry['quantity']
                is_parcel = entry.get('is_parcel', False)
                is_fried = entry.get('is_fried', False) and menu_item.supports_fried_option
                has_extra_cheese = entry.get('has_extra_cheese', False) and menu_item.supports_cheese_option

                order_item, created = OrderItem.objects.get_or_create(
                    order=order, menu_item=menu_item,
                    is_parcel=is_parcel, is_fried=is_fried, has_extra_cheese=has_extra_cheese,
                    defaults={'quantity': quantity},
                )
                if not created:
                    order_item.quantity += quantity
                    order_item.save()

        # The `order` instance still holds its original (empty) prefetched
        # items from get_object(), so re-fetch it fresh before serializing —
        # otherwise the response won't reflect the items we just added.
        order = self.get_queryset().get(pk=order.pk)
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def set_item_quantity(self, request, pk=None):
        """
        Sets a line item to an EXACT quantity — use this for +/- adjustments
        or removing an item (quantity=0), as opposed to add_items which is
        always incremental (adds to whatever's already there).
        """
        order = self.get_object()
        if order.status != Order.Status.OPEN:
            return Response(
                {'detail': f"Cannot modify an order with status '{order.status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = SetItemQuantitySerializer(data=request.data)
        self._scope_menu_item_field(serializer)
        serializer.is_valid(raise_exception=True)
        menu_item = serializer.validated_data['menu_item']
        quantity = serializer.validated_data['quantity']
        is_parcel = serializer.validated_data.get('is_parcel', False)
        is_fried = serializer.validated_data.get('is_fried', False) and menu_item.supports_fried_option
        has_extra_cheese = serializer.validated_data.get('has_extra_cheese', False) and menu_item.supports_cheese_option

        with transaction.atomic():
            if quantity == 0:
                OrderItem.objects.filter(
                    order=order, menu_item=menu_item,
                    is_parcel=is_parcel, is_fried=is_fried, has_extra_cheese=has_extra_cheese,
                ).delete()
            else:
                OrderItem.objects.update_or_create(
                    order=order, menu_item=menu_item,
                    is_parcel=is_parcel, is_fried=is_fried, has_extra_cheese=has_extra_cheese,
                    defaults={'quantity': quantity},
                )

        order = self.get_queryset().get(pk=order.pk)
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def voice_add(self, request, pk=None):
        """
        POST /api/orders/{id}/voice_add/
        Body: {"text": "two chicken burgers extra cheese"}
        Parses the text against this shop's active menu and adds whatever
        it can confidently match. Anything it's unsure about comes back
        in "needs_review" instead of being silently added wrong.
        """
        from .voice_parsing import parse_order_text, MATCH_THRESHOLD

        order = self.get_object()
        if order.status != Order.Status.OPEN:
            return Response(
                {'detail': f"Cannot add items to an order with status '{order.status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        text = (request.data.get('text') or '').strip()
        if not text:
            return Response({'detail': "No speech text given."}, status=status.HTTP_400_BAD_REQUEST)

        menu_items = list(MenuItem.objects.filter(shop=order.shop, is_active=True))
        parsed = parse_order_text(text, menu_items)

        added = []
        needs_review = []

        with transaction.atomic():
            for entry in parsed:
                menu_item = entry['menu_item']
                if menu_item is not None and entry['match_score'] >= MATCH_THRESHOLD:
                    is_fried = entry['is_fried'] and menu_item.supports_fried_option
                    has_extra_cheese = entry['has_extra_cheese'] and menu_item.supports_cheese_option
                    order_item, created = OrderItem.objects.get_or_create(
                        order=order, menu_item=menu_item,
                        is_parcel=entry['is_parcel'], is_fried=is_fried, has_extra_cheese=has_extra_cheese,
                        defaults={'quantity': entry['quantity']},
                    )
                    if not created:
                        order_item.quantity += entry['quantity']
                        order_item.save()
                    added.append({'raw': entry['raw'], 'menu_item': menu_item.name, 'quantity': entry['quantity']})
                else:
                    needs_review.append({
                        'raw': entry['raw'],
                        'best_guess': menu_item.name if menu_item else None,
                        'match_score': entry['match_score'],
                    })

        order = self.get_queryset().get(pk=order.pk)
        return Response({
            'order': OrderSerializer(order).data,
            'added': added,
            'needs_review': needs_review,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def set_dining_mode(self, request, pk=None):
        """
        POST /api/orders/{id}/set_dining_mode/
        Body: {"is_parcel": true}  — true for takeaway (+Rs.5/item), false
        for dine-in. Applies to EVERY item currently in the order (this is
        meant to be called once at checkout, not per item), recomputing
        each item's price. Rows that would become duplicates after the
        change (same menu item + fried/cheese, differing only by the old
        is_parcel value) are merged into one.
        """
        order = self.get_object()
        if order.status != Order.Status.OPEN:
            return Response(
                {'detail': f"Cannot modify an order with status '{order.status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        is_parcel = bool(request.data.get('is_parcel', False))

        with transaction.atomic():
            merged = {}
            for item in order.items.all():
                key = (item.menu_item_id, item.is_fried, item.has_extra_cheese)
                merged[key] = merged.get(key, 0) + item.quantity

            order.items.all().delete()
            for (menu_item_id, is_fried, has_extra_cheese), quantity in merged.items():
                OrderItem.objects.create(
                    order=order, menu_item_id=menu_item_id,
                    is_parcel=is_parcel, is_fried=is_fried, has_extra_cheese=has_extra_cheese,
                    quantity=quantity,
                )

        order = self.get_queryset().get(pk=order.pk)
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def generate_bill(self, request, pk=None):
        order = self.get_object()

        if order.status != Order.Status.OPEN:
            return Response(
                {'detail': f"Order already has status '{order.status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not order.items.exists():
            return Response({'detail': "Cannot bill an order with no items."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = GenerateBillSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tax_rate = serializer.validated_data.get('tax_rate', Decimal('0.00'))
        payment_method = serializer.validated_data.get('payment_method', Bill.PaymentMethod.CASH)

        with transaction.atomic():
            subtotal = order.subtotal
            tax_amount = (subtotal * tax_rate / Decimal('100')).quantize(Decimal('0.01'))
            total = subtotal + tax_amount

            bill = Bill.objects.create(
                order=order,
                subtotal=subtotal,
                tax_rate=tax_rate,
                tax_amount=tax_amount,
                total=total,
                payment_method=payment_method,
            )
            order.status = Order.Status.BILLED
            order.save()

            # Auto-deduct stock: for each item sold, walk its recipe and
            # reduce each ingredient by (quantity_required * quantity sold).
            # We deliberately allow this to go negative rather than block
            # billing — a negative/very-low stock number is exactly the
            # signal the reorder agent will act on.
            for order_item in order.items.select_related('menu_item').all():
                recipe_lines = RecipeMap.objects.filter(menu_item=order_item.menu_item).select_related('ingredient')
                for line in recipe_lines:
                    ingredient = line.ingredient
                    ingredient.current_stock -= (line.quantity_required * order_item.quantity)
                    ingredient.save()

        return Response(BillSerializer(bill).data, status=status.HTTP_201_CREATED)

    def _scope_menu_item_field(self, serializer):
        """Restricts the menu_item PK field (single or many=True list serializer) to the current shop."""
        shop = self.get_current_shop()
        scoped_qs = MenuItem.objects.filter(shop=shop)
        target = serializer.child if hasattr(serializer, 'child') else serializer
        if 'menu_item' in target.fields:
            target.fields['menu_item'].queryset = scoped_qs


class BillViewSet(TenantScopedMixin, viewsets.ReadOnlyModelViewSet):
    """
    GET /api/bills/          list all bills, most recent first
    GET /api/bills/today/    just today's bills — what you'll check at closing time
    GET /api/bills/{id}/     retrieve one bill
    """
    queryset = Bill.objects.select_related('order').prefetch_related('order__items__menu_item').all()
    serializer_class = BillSerializer
    shop_lookup = 'order__shop'

    @action(detail=True, methods=['post'])
    def send_whatsapp(self, request, pk=None):
        """
        POST /api/bills/{id}/send_whatsapp/
        Body (optional): {"phone": "919876543210"} — overrides the order's
        saved customer_phone. Sends the bill as a WhatsApp text message
        directly via Twilio (no redirect to the WhatsApp app).
        """
        from .notifications import send_whatsapp_to_number

        bill = self.get_object()
        order = bill.order
        phone = (request.data.get('phone') or order.customer_phone or '').strip()
        phone = ''.join(ch for ch in phone if ch.isdigit())

        if not phone:
            return Response({'detail': "No phone number on file for this order."}, status=status.HTTP_400_BAD_REQUEST)

        lines = "\n".join(
            f"{item.display_name} x{item.quantity} - Rs.{item.line_total}"
            for item in order.items.all()
        )
        payment_label = dict(Bill.PaymentMethod.choices).get(bill.payment_method, bill.payment_method)
        message = (
            f"*{order.shop.name}*\n"
            f"Bill #{bill.id} - {bill.created_at.strftime('%d %b %Y, %I:%M %p')}\n\n"
            f"{lines}\n\n"
            f"Subtotal: Rs.{bill.subtotal}\n"
            + (f"Tax: Rs.{bill.tax_amount}\n" if bill.tax_amount > 0 else "")
            + f"*Total: Rs.{bill.total}*\n"
            f"Paid via: {payment_label}\n\n"
            f"Thank you for your order!"
        )

        sent = send_whatsapp_to_number(phone, message)
        if sent:
            return Response({'sent': True})
        return Response(
            {'sent': False, 'detail': "WhatsApp send failed — check Twilio credentials, and that this number has joined your Twilio WhatsApp sandbox (or that you have an approved WhatsApp Business sender)."},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    @action(detail=False, methods=['get'])
    def today(self, request):
        now = timezone.localtime()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        todays_bills = self.get_queryset().filter(created_at__gte=start_of_day)

        page = self.paginate_queryset(todays_bills)
        serializer = self.get_serializer(page if page is not None else todays_bills, many=True)
        data = serializer.data

        total_sales = sum((b.total for b in todays_bills), Decimal('0.00'))

        # Payment-method breakdown — this is the end-of-day audit split:
        # cash in the box should match cash_total, UPI should match your
        # payment app's dashboard for the day.
        by_method = {method: Decimal('0.00') for method, _ in Bill.PaymentMethod.choices}
        by_method_count = {method: 0 for method, _ in Bill.PaymentMethod.choices}
        for b in todays_bills:
            by_method[b.payment_method] += b.total
            by_method_count[b.payment_method] += 1

        response_payload = {
            'date': now.date().isoformat(),
            'bill_count': todays_bills.count(),
            'total_sales': str(total_sales),
            'cash_total': str(by_method.get(Bill.PaymentMethod.CASH, Decimal('0.00'))),
            'cash_bill_count': by_method_count.get(Bill.PaymentMethod.CASH, 0),
            'upi_total': str(by_method.get(Bill.PaymentMethod.UPI, Decimal('0.00'))),
            'upi_bill_count': by_method_count.get(Bill.PaymentMethod.UPI, 0),
            'other_total': str(by_method.get(Bill.PaymentMethod.OTHER, Decimal('0.00'))),
            'other_bill_count': by_method_count.get(Bill.PaymentMethod.OTHER, 0),
            'bills': data,
        }
        if page is not None:
            return self.get_paginated_response(response_payload)
        return Response(response_payload)


class IngredientViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    """
    GET/POST   /api/ingredients/             list / create ingredients
    PATCH      /api/ingredients/{id}/        adjust stock, threshold, etc.
    GET        /api/ingredients/low_stock/   ingredients at or below their reorder threshold
    """
    queryset = Ingredient.objects.all()
    serializer_class = IngredientSerializer

    @action(detail=False, methods=['get'])
    def low_stock(self, request):
        low = [i for i in self.get_queryset() if i.is_low_stock]
        serializer = self.get_serializer(low, many=True)
        return Response({'count': len(low), 'ingredients': serializer.data})


class RecipeMapViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    """
    GET/POST   /api/recipe-map/             list / create recipe lines
    PATCH      /api/recipe-map/{id}/        adjust quantity_required
    GET        /api/recipe-map/?menu_item=1 filter recipe lines for one menu item
    """
    queryset = RecipeMap.objects.select_related('menu_item', 'ingredient').all()
    serializer_class = RecipeMapSerializer
    shop_lookup = 'menu_item__shop'

    def get_queryset(self):
        qs = super().get_queryset()
        menu_item_id = self.request.query_params.get('menu_item')
        if menu_item_id:
            qs = qs.filter(menu_item_id=menu_item_id)
        return qs

    def get_serializer(self, *args, **kwargs):
        serializer = super().get_serializer(*args, **kwargs)
        # A recipe line must connect a menu item and an ingredient that both
        # belong to the current shop — scope both PK fields accordingly.
        shop = self.get_current_shop()
        serializer.fields['menu_item'].queryset = MenuItem.objects.filter(shop=shop)
        serializer.fields['ingredient'].queryset = Ingredient.objects.filter(shop=shop)
        return serializer


class DemandForecastViewSet(TenantScopedMixin, viewsets.ReadOnlyModelViewSet):
    """
    GET /api/forecasts/                    list all forecasts, most recent first
    GET /api/forecasts/?forecast_date=2026-07-24   filter to one date
    GET /api/forecasts/{id}/               retrieve one forecast
    """
    queryset = DemandForecast.objects.select_related('menu_item').all()
    serializer_class = DemandForecastSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        forecast_date = self.request.query_params.get('forecast_date')
        if forecast_date:
            qs = qs.filter(forecast_date=forecast_date)
        return qs


class AgentLogViewSet(TenantScopedMixin, viewsets.ReadOnlyModelViewSet):
    """
    GET  /api/agent-logs/                       list all agent decisions, most recent first
    GET  /api/agent-logs/?decision=critical      filter by decision type
    GET  /api/agent-logs/?run_date=2026-07-23    filter by the day the agent ran
    POST /api/agent-logs/{id}/send_whatsapp/     manually send this log's drafted message via WhatsApp
    """
    queryset = AgentLog.objects.select_related('ingredient').all()
    serializer_class = AgentLogSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        decision = self.request.query_params.get('decision')
        if decision:
            qs = qs.filter(decision=decision)
        run_date = self.request.query_params.get('run_date')
        if run_date:
            qs = qs.filter(run_date=run_date)
        return qs

    @action(detail=True, methods=['post'])
    def send_whatsapp(self, request, pk=None):
        """Manually sends this log's message_draft via WhatsApp — for low-stock drafts you review and approve, or retrying a failed critical send."""
        from .notifications import send_whatsapp_message

        log = self.get_object()
        if not log.message_draft:
            return Response({'detail': "This decision has no message to send."}, status=status.HTTP_400_BAD_REQUEST)

        sent = send_whatsapp_message(log.ingredient, log.message_draft)
        if sent:
            log.action_taken = AgentLog.ActionTaken.MESSAGE_SENT
            log.message_channel = AgentLog.Channel.WHATSAPP
            log.save(update_fields=['action_taken', 'message_channel'])
            return Response(AgentLogSerializer(log).data)

        return Response(
            {'detail': "WhatsApp send failed — check Twilio credentials and the supplier's WhatsApp number are set."},
            status=status.HTTP_502_BAD_GATEWAY,
        )


class DemandAnomalyViewSet(TenantScopedMixin, viewsets.ReadOnlyModelViewSet):
    """
    GET /api/anomalies/                        list all anomaly evaluations, most recent first
    GET /api/anomalies/?flag=over_forecast      filter by flag
    """
    queryset = DemandAnomaly.objects.select_related('menu_item').all()
    serializer_class = DemandAnomalySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        flag = self.request.query_params.get('flag')
        if flag:
            qs = qs.filter(flag=flag)
        return qs


class WeeklySummaryReportViewSet(TenantScopedMixin, viewsets.ReadOnlyModelViewSet):
    """GET /api/weekly-summaries/  list weekly reports, most recent first"""
    queryset = WeeklySummaryReport.objects.all()
    serializer_class = WeeklySummaryReportSerializer