from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def fcfa(valeur, suffixe=True):
    """1157926221 -> « 1 157 926 221 F CFA » (espaces insécables)."""
    if valeur in (None, ""):
        return "—"
    try:
        n = int(Decimal(valeur))
    except Exception:
        return valeur
    texte = f"{n:,}".replace(",", "\u202f")
    return f"{texte}\u00a0F\u00a0CFA" if suffixe else texte


@register.filter
def millions(valeur):
    """Format court pour les gros montants : « 1 157,9 M »."""
    if valeur in (None, ""):
        return "—"
    n = Decimal(valeur) / Decimal(1_000_000)
    texte = f"{n:,.1f}".replace(",", "\u202f").replace(".", ",")
    return f"{texte}\u00a0M"


@register.filter
def jours(n):
    if n is None:
        return ""
    if n < 0:
        return f"en retard de {-n} j"
    if n == 0:
        return "aujourd'hui"
    if n == 1:
        return "demain"
    return f"dans {n} j"
