from datetime import date, datetime
from decimal import Decimal

from django import template
from django.utils import timezone

register = template.Library()

THAI_MONTHS = (
    "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
    "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.",
)


@register.filter
def money(value) -> str:
    if value in (None, ""):
        return ""
    return f"{Decimal(value):,.2f}"


@register.filter
def quantity(value) -> str:
    if value in (None, ""):
        return ""
    return f"{Decimal(value):,.3f}".rstrip("0").rstrip(".")


@register.filter
def percent(value) -> str:
    if value in (None, ""):
        return ""
    return f"{Decimal(value):.2f}".rstrip("0").rstrip(".") + "%"


@register.filter
def thai_date(value) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        value = timezone.localtime(value).date()
    if not isinstance(value, date):
        return str(value)
    return f"{value.day} {THAI_MONTHS[value.month - 1]} {value.year + 543}"


@register.filter
def thai_datetime(value) -> str:
    if not value:
        return ""
    local = timezone.localtime(value)
    return f"{thai_date(local.date())} {local:%H:%M} น."
