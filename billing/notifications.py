"""
Sends the reorder message to a supplier.

Two channels:
- WhatsApp (primary) via Twilio's WhatsApp API. Twilio has a free sandbox
  you can start with immediately (no Meta Business verification needed) —
  see the setup notes in README / .env.example.
- Email (fallback) via Django's email backend — console backend in dev, so
  the message prints to your terminal.

Both functions return False (and log a clear reason) rather than raising,
if the relevant credentials aren't configured yet — so the reorder agent
never crashes just because you haven't set up messaging.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_whatsapp_to_number(to_number: str, message: str) -> bool:
    """
    Generic WhatsApp send to any number via Twilio — used for customer bills
    (as opposed to send_whatsapp_message, which is supplier-specific).
    Returns True only if Twilio confirms the message was accepted for sending.

    Note on limits: Twilio's WhatsApp sandbox can only message numbers that
    have joined the sandbox (by texting the join code to the sandbox
    number) — fine for testing, not for real customers. For real customers
    you need a Meta-approved WhatsApp Business sender via Twilio; even then,
    a business-initiated message like a bill (outside a customer-initiated
    24-hour session) must use a pre-approved message template, not free text.
    """
    account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', '')
    auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')
    from_number = getattr(settings, 'TWILIO_WHATSAPP_FROM', '')

    if not (account_sid and auth_token and from_number):
        logger.warning(
            "WhatsApp not sent to %s: Twilio credentials not configured "
            "(set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM in .env).",
            to_number,
        )
        return False

    if not to_number:
        logger.warning("WhatsApp not sent: no destination phone number given.")
        return False

    try:
        from twilio.rest import Client

        client = Client(account_sid, auth_token)
        client.messages.create(
            from_=f"whatsapp:{from_number}" if not from_number.startswith('whatsapp:') else from_number,
            to=f"whatsapp:{to_number}" if not to_number.startswith('whatsapp:') else to_number,
            body=message,
        )
        return True
    except Exception as exc:
        logger.error("Failed to send WhatsApp message to %s: %s", to_number, exc)
        return False


def send_whatsapp_message(ingredient, message: str) -> bool:
    """
    Sends `message` to ingredient.supplier_whatsapp via Twilio's WhatsApp API.
    Returns True only if Twilio confirms the message was accepted for sending.
    """
    account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', '')
    auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')
    from_number = getattr(settings, 'TWILIO_WHATSAPP_FROM', '')

    if not (account_sid and auth_token and from_number):
        logger.warning(
            "WhatsApp not sent for %s: Twilio credentials not configured "
            "(set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM in .env).",
            ingredient.name,
        )
        return False

    if not ingredient.supplier_whatsapp:
        logger.warning(
            "WhatsApp not sent for %s: no supplier_whatsapp number on file for this ingredient.",
            ingredient.name,
        )
        return False

    try:
        from twilio.rest import Client

        client = Client(account_sid, auth_token)
        client.messages.create(
            from_=f"whatsapp:{from_number}" if not from_number.startswith('whatsapp:') else from_number,
            to=f"whatsapp:{ingredient.supplier_whatsapp}" if not ingredient.supplier_whatsapp.startswith('whatsapp:') else ingredient.supplier_whatsapp,
            body=message,
        )
        return True
    except Exception as exc:
        logger.error("Failed to send WhatsApp message for %s: %s", ingredient.name, exc)
        return False


def send_supplier_message_email(ingredient, message: str) -> bool:
    """Fallback channel: email. Returns True if at least attempted without error."""
    subject = f"[{ingredient.shop.name}] Reorder needed: {ingredient.name}"
    recipient = ingredient.supplier_contact or "no-supplier-contact-on-file"

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'tastyzone@example.com'),
            recipient_list=[recipient] if '@' in recipient else ['ops@tastyzone.local'],
            fail_silently=False,
        )
        return True
    except Exception as exc:
        logger.error("Failed to send supplier email for %s: %s", ingredient.name, exc)
        return False


def send_supplier_message(ingredient, message: str) -> tuple[bool, str]:
    """
    Tries WhatsApp first (the real channel you'd use with a supplier), falls
    back to email if WhatsApp isn't configured or fails. Returns (sent, channel).
    """
    if send_whatsapp_message(ingredient, message):
        return True, 'whatsapp'
    if send_supplier_message_email(ingredient, message):
        return True, 'email'
    return False, 'none'