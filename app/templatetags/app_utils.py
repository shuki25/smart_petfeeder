from django import template

from app.utils import xss_token

register = template.Library()


@register.filter
def bitwise_and(value, arg):
    return 1 if value & arg else 0


@register.filter
def xss_tokenize(value, arg):
    return xss_token(arg, value)
