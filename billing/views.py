import logging

from datetime import datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, F, Sum
from django.db.models.functions import ExtractHour, TruncDate
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

    def perform_create(self, serializer):
        try:
            super().perform_create(serializer)
        except Exception as exc:
            logging.getLogger(__name__).exception("Failed to create menu item")
            raise ValidationError({'detail': f'Could not save this item: {exc}'})

    def perform_update(self, serializer):
        try:
            super().perform_update(serializer)
        except Exception as exc:
            logging.getLogger(__name__).exception("Failed to update menu item id=%s", serializer.instance.id)
            raise ValidationError({'detail': f'Could not save this item: {exc}'})


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
    def toggle_item_parcel(self, request, pk=None):
        """
        POST /api/orders/{id}/toggle_item_parcel/
        Body: {"menu_item": id, "is_fried": bool, "has_extra_cheese": bool, "current_is_parcel": bool}
        — describes the exact row as it exists right now. Flips that row's
        is_parcel (dine-in <-> takeaway, +/- Rs.5/unit), moving its whole
        quantity to the opposite version and merging into a matching row if
        one already exists. This is per-item on purpose: one order can be
        part dine-in, part parcel (e.g. one person eating in, one taking
        food to go).
        """
        order = self.get_object()
        if order.status != Order.Status.OPEN:
            return Response(
                {'detail': f"Cannot modify an order with status '{order.status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        menu_item_id = request.data.get('menu_item')
        is_fried = bool(request.data.get('is_fried', False))
        has_extra_cheese = bool(request.data.get('has_extra_cheese', False))
        current_is_parcel = bool(request.data.get('current_is_parcel', False))
        new_is_parcel = not current_is_parcel

        with transaction.atomic():
            try:
                source = OrderItem.objects.get(
                    order=order, menu_item_id=menu_item_id,
                    is_fried=is_fried, has_extra_cheese=has_extra_cheese, is_parcel=current_is_parcel,
                )
            except OrderItem.DoesNotExist:
                return Response({'detail': 'That item is not in this order.'}, status=status.HTTP_404_NOT_FOUND)

            quantity = source.quantity
            source.delete()

            target, created = OrderItem.objects.get_or_create(
                order=order, menu_item_id=menu_item_id,
                is_fried=is_fried, has_extra_cheese=has_extra_cheese, is_parcel=new_is_parcel,
                defaults={'quantity': quantity},
            )
            if not created:
                target.quantity += quantity
                target.save()

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
        cash_amount = serializer.validated_data.get('cash_amount')
        upi_amount = serializer.validated_data.get('upi_amount')

        with transaction.atomic():
            subtotal = order.subtotal
            tax_amount = (subtotal * tax_rate / Decimal('100')).quantize(Decimal('0.01'))
            total = subtotal + tax_amount

            if payment_method == Bill.PaymentMethod.SPLIT:
                if cash_amount is None or upi_amount is None:
                    return Response(
                        {'detail': "Split payment needs both cash_amount and upi_amount."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if (cash_amount + upi_amount) != total:
                    return Response(
                        {'detail': f"Cash ({cash_amount}) + GPay ({upi_amount}) must add up to the bill total ({total})."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                cash_amount = None
                upi_amount = None

            bill = Bill.objects.create(
                order=order,
                subtotal=subtotal,
                tax_rate=tax_rate,
                tax_amount=tax_amount,
                total=total,
                payment_method=payment_method,
                cash_amount=cash_amount,
                upi_amount=upi_amount,
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

    @action(detail=False, methods=['get'])
    def history(self, request):
        """
        GET /api/bills/history/
        GET /api/bills/history/?date=2026-08-15
        Without ?date: returns yesterday's and today's totals (for a quick
        glance), plus a day-by-day total for the last 30 days — like a
        payment app's transaction history.
        With ?date=YYYY-MM-DD: returns every bill from that specific day,
        each with its full item breakdown, so you can see exactly what
        each order bought.
        """
        from datetime import timedelta
        qs = self.get_queryset()

        date_param = request.query_params.get('date')
        if date_param:
            try:
                target_date = datetime.strptime(date_param, '%Y-%m-%d').date()
            except ValueError:
                return Response({'detail': 'date must be in YYYY-MM-DD format.'}, status=status.HTTP_400_BAD_REQUEST)
            days_bills = qs.filter(created_at__date=target_date).order_by('daily_number')
            serializer = self.get_serializer(days_bills, many=True)
            total = sum((b.total for b in days_bills), Decimal('0.00'))
            return Response({
                'date': target_date.isoformat(),
                'total': str(total),
                'bill_count': days_bills.count(),
                'bills': serializer.data,
            })

        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        thirty_days_ago = today - timedelta(days=29)

        def day_summary(day):
            agg = qs.filter(created_at__date=day).aggregate(total=Sum('total'), count=Count('id'))
            return {'date': day.isoformat(), 'total': str(agg['total'] or Decimal('0.00')), 'bill_count': agg['count'] or 0}

        daily = (
            qs.filter(created_at__date__gte=thirty_days_ago)
            .annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(total=Sum('total'), count=Count('id'))
            .order_by('-day')
        )
        daily_totals = [{'date': str(row['day']), 'total': str(row['total']), 'bill_count': row['count']} for row in daily]

        return Response({
            'today': day_summary(today),
            'yesterday': day_summary(yesterday),
            'daily_totals': daily_totals,
        })

    @action(detail=False, methods=['get'])
    def analytics(self, request):
        """
        GET /api/bills/analytics/?days=30
        The "spending insights" page — sales trend over the period, your
        best-selling items, revenue by menu category, cash/GPay/split
        breakdown, and which hours of the day are busiest.
        """
        from datetime import timedelta

        try:
            days = int(request.query_params.get('days', 30))
        except ValueError:
            days = 30
        days = max(1, min(days, 90))

        today = timezone.localdate()
        start_date = today - timedelta(days=days - 1)

        qs = self.get_queryset().filter(created_at__date__gte=start_date)

        # Daily sales trend, oldest first (good for a left-to-right chart).
        daily = (
            qs.annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(total=Sum('total'), count=Count('id'))
            .order_by('day')
        )
        daily_by_date = {str(row['day']): row for row in daily}
        trend = []
        for i in range(days):
            d = start_date + timedelta(days=i)
            row = daily_by_date.get(str(d))
            trend.append({
                'date': d.isoformat(),
                'total': str(row['total']) if row else '0.00',
                'bill_count': row['count'] if row else 0,
            })

        # Payment method breakdown — split bills count their two halves
        # toward cash/upi separately, same logic as the today/ endpoint.
        cash_total = upi_total = other_total = Decimal('0.00')
        for b in qs:
            if b.payment_method == Bill.PaymentMethod.SPLIT:
                cash_total += b.cash_amount or Decimal('0.00')
                upi_total += b.upi_amount or Decimal('0.00')
            elif b.payment_method == Bill.PaymentMethod.CASH:
                cash_total += b.total
            elif b.payment_method == Bill.PaymentMethod.UPI:
                upi_total += b.total
            else:
                other_total += b.total

        # Best-selling items, by revenue — join through Order to reach
        # OrderItem for bills in this window.
        order_ids = qs.values_list('order_id', flat=True)
        item_rows = (
            OrderItem.objects.filter(order_id__in=order_ids)
            .values('menu_item__name')
            .annotate(
                quantity=Sum('quantity'),
                revenue=Sum(F('unit_price') * F('quantity')),
            )
            .order_by('-revenue')[:8]
        )
        top_items = [
            {'name': row['menu_item__name'], 'quantity': row['quantity'], 'revenue': str(row['revenue'] or Decimal('0.00'))}
            for row in item_rows
        ]

        # Revenue by menu category.
        category_rows = (
            OrderItem.objects.filter(order_id__in=order_ids)
            .values('menu_item__category')
            .annotate(revenue=Sum(F('unit_price') * F('quantity')))
            .order_by('-revenue')
        )
        category_breakdown = [
            {'category': row['menu_item__category'], 'revenue': str(row['revenue'] or Decimal('0.00'))}
            for row in category_rows
        ]

        # Busiest hours of the day (0-23), by bill count.
        hour_rows = (
            qs.annotate(hour=ExtractHour('created_at'))
            .values('hour')
            .annotate(count=Count('id'))
            .order_by('hour')
        )
        hour_counts = {row['hour']: row['count'] for row in hour_rows}
        peak_hours = [{'hour': h, 'count': hour_counts.get(h, 0)} for h in range(24)]

        total_revenue = sum((Decimal(t['total']) for t in trend), Decimal('0.00'))
        total_bills = sum((t['bill_count'] for t in trend), 0)

        return Response({
            'period_days': days,
            'start_date': start_date.isoformat(),
            'end_date': today.isoformat(),
            'total_revenue': str(total_revenue),
            'total_bills': total_bills,
            'avg_bill_value': str((total_revenue / total_bills).quantize(Decimal('0.01'))) if total_bills else '0.00',
            'daily_trend': trend,
            'payment_breakdown': {
                'cash': str(cash_total),
                'upi': str(upi_total),
                'other': str(other_total),
            },
            'top_items': top_items,
            'category_breakdown': category_breakdown,
            'peak_hours': peak_hours,
        })

    @action(detail=False, methods=['get'])
    def daily_goal(self, request):
        """
        GET /api/bills/daily_goal/
        Today's progress toward the shop's daily revenue target (set in
        Shop Settings), plus a streak of consecutive days the target was
        hit. Returns target=None if no target has been set yet.
        """
        shop = self.get_current_shop()
        target = shop.daily_revenue_target
        if target is None:
            return Response({'target': None})

        qs = self.get_queryset()
        today = timezone.localdate()

        def day_total(d):
            return qs.filter(created_at__date=d).aggregate(total=Sum('total'))['total'] or Decimal('0.00')

        todays_total = day_total(today)
        hit_today = todays_total >= target

        # Walk backward counting consecutive target-hit days, starting from
        # today (if already hit) or yesterday otherwise.
        streak = 0
        check_date = today if hit_today else today - timedelta(days=1)
        for _ in range(365):
            if day_total(check_date) >= target:
                streak += 1
                check_date -= timedelta(days=1)
            else:
                break

        return Response({
            'target': str(target),
            'today_total': str(todays_total),
            'progress_pct': min(100, round(float(todays_total / target) * 100)) if target > 0 else 0,
            'hit_today': hit_today,
            'streak': streak,
        })

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
        # payment app's dashboard for the day. Split-payment bills count
        # their cash_amount toward cash_total and upi_amount toward
        # upi_total (not the whole bill toward one or the other).
        cash_total = Decimal('0.00')
        cash_bill_count = 0
        upi_total = Decimal('0.00')
        upi_bill_count = 0
        other_total = Decimal('0.00')
        other_bill_count = 0

        for b in todays_bills:
            if b.payment_method == Bill.PaymentMethod.SPLIT:
                cash_total += b.cash_amount or Decimal('0.00')
                upi_total += b.upi_amount or Decimal('0.00')
                cash_bill_count += 1
                upi_bill_count += 1
            elif b.payment_method == Bill.PaymentMethod.CASH:
                cash_total += b.total
                cash_bill_count += 1
            elif b.payment_method == Bill.PaymentMethod.UPI:
                upi_total += b.total
                upi_bill_count += 1
            else:
                other_total += b.total
                other_bill_count += 1

        response_payload = {
            'date': now.date().isoformat(),
            'bill_count': todays_bills.count(),
            'total_sales': str(total_sales),
            'cash_total': str(cash_total),
            'cash_bill_count': cash_bill_count,
            'upi_total': str(upi_total),
            'upi_bill_count': upi_bill_count,
            'other_total': str(other_total),
            'other_bill_count': other_bill_count,
            'bills': data,
        }
        if page is not None:
            return self.get_paginated_response(response_payload)
        return Response(response_payload)

    @action(detail=False, methods=['get'])
    def revenue_summary(self, request):
        """
        GET /api/bills/revenue_summary/
        The overall business snapshot — total revenue and bill count for
        today, this week (Mon-Sun), this month, this year, and all-time.
        Used for the dashboard's revenue report section.
        """
        now = timezone.localtime()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)
        year_start = today_start.replace(month=1, day=1)

        qs = self.get_queryset()

        def summarize(filtered_qs):
            agg = filtered_qs.aggregate(total=Sum('total'), count=Count('id'))
            return {
                'total': str(agg['total'] or Decimal('0.00')),
                'bill_count': agg['count'] or 0,
            }

        return Response({
            'today': summarize(qs.filter(created_at__gte=today_start)),
            'this_week': summarize(qs.filter(created_at__gte=week_start)),
            'this_month': summarize(qs.filter(created_at__gte=month_start)),
            'this_year': summarize(qs.filter(created_at__gte=year_start)),
            'all_time': summarize(qs),
        })


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