"""
Envoi des alertes.

- E-mail : récapitulatif quotidien (gratuit), canal principal.
- SMS / WhatsApp : réservés aux cas critiques (chèques à J-3 et le jour J,
  échéances en retard, impayés), plafonnés chaque mois. Désactivés par
  défaut : branchez votre fournisseur dans `envoyer_sms()`.
"""
import logging
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone

from .models import Echeance, EnvoiRecap, SmsEnvoye

log = logging.getLogger("echeances")

GROUPES_ALERTES = ["Gestionnaire", "Valideur"]


def destinataires(groupes=GROUPES_ALERTES):
    User = get_user_model()
    return (User.objects.filter(is_active=True).exclude(email="")
            .filter(Q(groups__name__in=groupes) | Q(is_superuser=True)).distinct())


def construire_recap(jour=None):
    jour = jour or timezone.localdate()
    ouvertes = Echeance.objects.ouvertes().select_related("banque", "fournisseur")
    paliers = []
    for p in sorted(settings.ALERTE_PALIERS, reverse=True):
        if p == 0:
            continue
        lst = list(ouvertes.filter(date_echeance=jour + timedelta(days=p)))
        if lst:
            paliers.append({"jours": p, "echeances": lst, "total": sum(e.montant_total for e in lst)})
    retard = list(ouvertes.filter(date_echeance__lt=jour))
    aujourdhui = list(ouvertes.filter(date_echeance=jour))
    semaine = list(ouvertes.entre(jour, jour + timedelta(days=7)))
    return {
        "jour": jour,
        "retard": retard, "total_retard": sum(e.montant_total for e in retard),
        "aujourdhui": aujourdhui, "total_aujourdhui": sum(e.montant_total for e in aujourdhui),
        "paliers": paliers,
        "nb_semaine": len(semaine), "total_semaine": sum(e.montant_total for e in semaine),
        "site_url": settings.SITE_URL.rstrip("/"),
    }


def recap_vide(ctx):
    return not (ctx["retard"] or ctx["aujourdhui"] or ctx["paliers"])


def envoyer_recap(jour=None, force=False, stdout=None):
    """Envoie le récapitulatif du jour à chaque destinataire. Retourne le nombre d'e-mails envoyés."""
    ctx = construire_recap(jour)
    if recap_vide(ctx):
        log.info("Rien à signaler aujourd'hui : aucun e-mail envoyé.")
        return 0
    nb_echeances = len(ctx["retard"]) + len(ctx["aujourdhui"]) + sum(len(p["echeances"]) for p in ctx["paliers"])
    sujet = _sujet(ctx)
    texte = render_to_string("emails/recap.txt", ctx)
    html = render_to_string("emails/recap.html", ctx)
    envoyes = 0
    for user in destinataires():
        if not force and EnvoiRecap.objects.filter(date=ctx["jour"], destinataire=user.email, canal="email").exists():
            continue
        msg = EmailMultiAlternatives(sujet, texte, settings.DEFAULT_FROM_EMAIL, [user.email])
        msg.attach_alternative(html, "text/html")
        msg.send()
        EnvoiRecap.objects.update_or_create(
            date=ctx["jour"], destinataire=user.email, canal="email",
            defaults={"nb_echeances": nb_echeances},
        )
        envoyes += 1
    _sms_critiques(ctx)
    return envoyes


def _sujet(ctx):
    morceaux = []
    if ctx["retard"]:
        morceaux.append(f"{len(ctx['retard'])} en retard")
    if ctx["aujourdhui"]:
        morceaux.append(f"{len(ctx['aujourdhui'])} aujourd'hui")
    if ctx["nb_semaine"]:
        morceaux.append(f"{ctx['nb_semaine']} dans les 7 jours")
    return "ÉchéancePro — " + ", ".join(morceaux or ["récapitulatif du jour"])


# --- Impayé : alerte immédiate aux valideurs -------------------------------------

def alerter_impaye(echeance):
    dest = [u.email for u in destinataires(["Valideur"])]
    if not dest:
        return
    ctx = {"e": echeance, "site_url": settings.SITE_URL.rstrip("/")}
    msg = EmailMultiAlternatives(
        f"ÉchéancePro — IMPAYÉ : {echeance.fournisseur} ({echeance.banque})",
        render_to_string("emails/impaye.txt", ctx), settings.DEFAULT_FROM_EMAIL, dest,
    )
    msg.send()
    _sms(f"ÉchéancePro : impayé {echeance.get_type_display()} {echeance.fournisseur} "
         f"{int(echeance.montant_total):,} F CFA ({echeance.banque}).".replace(",", " "))


# --- SMS / WhatsApp ----------------------------------------------------------

def _sms_critiques(ctx):
    critiques = [e for e in ctx["aujourdhui"] if e.type == Echeance.Type.CHEQUE]
    for p in ctx["paliers"]:
        if p["jours"] <= 3:
            critiques += [e for e in p["echeances"] if e.type == Echeance.Type.CHEQUE]
    if ctx["retard"]:
        _sms(f"ÉchéancePro : {len(ctx['retard'])} échéance(s) en retard, "
             f"{int(ctx['total_retard']):,} F CFA.".replace(",", " "))
    if critiques:
        total = sum(e.montant_total for e in critiques)
        _sms(f"ÉchéancePro : {len(critiques)} chèque(s) à couvrir sous 3 jours, "
             f"{int(total):,} F CFA.".replace(",", " "))


def _sms(texte):
    if not settings.SMS_ACTIF:
        return
    numeros = [n.strip() for n in os.getenv("SMS_DESTINATAIRES", "").split(",") if n.strip()]
    debut_mois = timezone.localdate().replace(day=1)
    deja = SmsEnvoye.objects.filter(envoye_le__date__gte=debut_mois).count()
    for numero in numeros:
        if deja >= settings.SMS_PLAFOND_MENSUEL:
            log.warning("Plafond mensuel de SMS atteint : message non envoyé.")
            return
        envoyer_sms(numero, texte)
        SmsEnvoye.objects.create(numero=numero, texte=texte)
        deja += 1


def envoyer_sms(numero, texte):
    """
    À brancher sur votre fournisseur SMS ou WhatsApp Business.
    Exemple (pseudo-code) :
        requests.post(URL_FOURNISSEUR, json={"to": numero, "text": texte},
                      headers={"Authorization": f"Bearer {os.getenv('SMS_API_KEY')}"})
    """
    log.info("SMS (simulation) vers %s : %s", numero, texte)
