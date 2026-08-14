"""
The reorder decision agent.

This is what makes the system "agentic" rather than a fixed pipeline: given
current stock + forecasted demand, it BRANCHES on its own judgment —
sufficient stock, low stock, or critical — and only escalates to messaging
a supplier when the situation actually calls for it. Every decision (even
"do nothing") gets logged with its reasoning in AgentLog.
"""
from datetime import date, timedelta
from decimal import Decimal

from .models import AgentLog, DemandForecast, Ingredient, RecipeMap
from .notifications import send_supplier_message

# How many days of lead time you assume a supplier needs — used to size
# the suggested reorder quantity. Tune this per ingredient later if needed.
SAFETY_STOCK_MULTIPLIER = Decimal('2.0')


def _predicted_demand_for_ingredient(ingredient: Ingredient, forecast_date: date) -> Decimal:
    """Sums forecasted consumption of this ingredient across every menu item that uses it."""
    total = Decimal('0.00')
    recipe_lines = RecipeMap.objects.filter(ingredient=ingredient).select_related('menu_item')

    for line in recipe_lines:
        forecast = DemandForecast.objects.filter(
            menu_item=line.menu_item, forecast_date=forecast_date,
        ).first()
        if forecast:
            total += line.quantity_required * forecast.predicted_quantity

    return total


def decide_for_ingredient(ingredient: Ingredient, forecast_date: date) -> AgentLog:
    """Makes (and logs) one reorder decision for one ingredient. Returns the AgentLog row."""
    predicted_demand = _predicted_demand_for_ingredient(ingredient, forecast_date)
    projected_stock = ingredient.current_stock - predicted_demand
    threshold = ingredient.reorder_threshold

    if projected_stock <= 0:
        decision = AgentLog.Decision.CRITICAL
        suggested_qty = (threshold * SAFETY_STOCK_MULTIPLIER) - projected_stock
        reasoning = (
            f"Projected stock after tomorrow's forecasted demand is {projected_stock}{ingredient.unit} "
            f"(current {ingredient.current_stock}{ingredient.unit} minus predicted demand "
            f"{predicted_demand}{ingredient.unit}) — at or below zero. This is urgent: "
            f"tomorrow's orders could run out mid-service. Sending a reorder message now."
        )
    elif ingredient.current_stock <= threshold or projected_stock <= threshold:
        decision = AgentLog.Decision.LOW_STOCK
        suggested_qty = (threshold * SAFETY_STOCK_MULTIPLIER) - projected_stock
        reasoning = (
            f"Current stock ({ingredient.current_stock}{ingredient.unit}) or projected stock after "
            f"tomorrow's demand ({projected_stock}{ingredient.unit}) is at/below the reorder threshold "
            f"({threshold}{ingredient.unit}). Not urgent yet, but a reorder should go out soon — "
            f"drafting the message for review rather than sending automatically."
        )
    else:
        decision = AgentLog.Decision.SUFFICIENT
        suggested_qty = Decimal('0.00')
        reasoning = (
            f"Current stock ({ingredient.current_stock}{ingredient.unit}) comfortably covers tomorrow's "
            f"predicted demand ({predicted_demand}{ingredient.unit}), leaving "
            f"{projected_stock}{ingredient.unit} — above the reorder threshold "
            f"({threshold}{ingredient.unit}). No action needed."
        )

    suggested_qty = max(Decimal('0.00'), suggested_qty).quantize(Decimal('0.01'))

    message_draft = ''
    action_taken = AgentLog.ActionTaken.NONE
    message_channel = AgentLog.Channel.NONE

    if decision in (AgentLog.Decision.LOW_STOCK, AgentLog.Decision.CRITICAL):
        message_draft = (
            f"Hi — this is an automated reorder note from {ingredient.shop.name}.\n\n"
            f"We're running low on {ingredient.name}. Current stock: {ingredient.current_stock}{ingredient.unit}.\n"
            f"Requesting approximately {suggested_qty}{ingredient.unit} to be delivered soon.\n\n"
            f"Thanks!"
        )
        if decision == AgentLog.Decision.CRITICAL:
            sent, channel = send_supplier_message(ingredient, message_draft)
            action_taken = AgentLog.ActionTaken.MESSAGE_SENT if sent else AgentLog.ActionTaken.MESSAGE_DRAFTED
            message_channel = channel if sent else AgentLog.Channel.NONE
        else:
            action_taken = AgentLog.ActionTaken.MESSAGE_DRAFTED
    else:
        action_taken = AgentLog.ActionTaken.LOGGED_ONLY

    return AgentLog.objects.create(
        shop=ingredient.shop,
        ingredient=ingredient,
        run_date=date.today(),
        decision=decision,
        action_taken=action_taken,
        message_channel=message_channel,
        current_stock=ingredient.current_stock,
        predicted_demand=predicted_demand,
        projected_stock_after_demand=projected_stock,
        suggested_order_quantity=suggested_qty,
        reasoning=reasoning,
        message_draft=message_draft,
    )


def run_reorder_agent(shop, forecast_date: date | None = None) -> list[AgentLog]:
    """Runs the reorder decision for every ingredient belonging to ONE shop. Meant to run daily, after the forecast."""
    if forecast_date is None:
        forecast_date = date.today() + timedelta(days=1)

    logs = []
    for ingredient in Ingredient.objects.filter(shop=shop):
        logs.append(decide_for_ingredient(ingredient, forecast_date))
    return logs
