"""Envoi d'e-mails : serveur SMTP réglé dans l'application (page « Alertes e-mail »), sinon réglages du serveur (.env).

Le mot de passe SMTP est enregistré chiffré (Fernet, clé dérivée de SECRET_KEY) et n'est jamais réaffiché.
"""
import base64
import hashlib
from email.utils import formataddr

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.mail import EmailMessage, get_connection

SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"


def _fernet():
    cle = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(cle)


def chiffrer(texte):
    return _fernet().encrypt(texte.encode()).decode()


def dechiffrer(jeton):
    """Texte en clair, ou None si absent ou illisible (SECRET_KEY changée depuis l'enregistrement)."""
    if not jeton:
        return None
    try:
        return _fernet().decrypt(jeton.encode()).decode()
    except InvalidToken:
        return None


def connexion_smtp(hote, port, securite, utilisateur="", mot_de_passe=None):
    return get_connection(
        backend=SMTP_BACKEND, host=hote, port=port,
        username=utilisateur or None, password=mot_de_passe or None,
        use_tls=securite == "tls", use_ssl=securite == "ssl", timeout=20,
    )


def connexion():
    """Connexion e-mail à utiliser : réglages de l'application si activés, sinon réglages du serveur."""
    from .models import ParametresAlertes

    p = ParametresAlertes.charger()
    if p.utilisable:
        return connexion_smtp(p.hote, p.port, p.securite, p.utilisateur, p.mot_de_passe())
    return get_connection()


def expediteur():
    from .models import ParametresAlertes

    p = ParametresAlertes.charger()
    if p.utilisable:
        return formataddr((p.expediteur_nom or "ÉchéancePro", p.expediteur_adresse))
    return settings.DEFAULT_FROM_EMAIL


def paliers():
    """Jours d'alerte avant l'échéance (les plus lointains d'abord)."""
    from .models import ParametresAlertes

    return ParametresAlertes.charger().liste_paliers()


def envoyer_test(destinataire, hote="", port=587, securite="tls", utilisateur="", mot_de_passe=None,
                 expediteur_nom="", expediteur_adresse=""):
    """Envoie un e-mail de test avec les réglages donnés (sans les enregistrer). Retourne (réussi, message)."""
    try:
        if hote:
            conn = connexion_smtp(hote, port, securite, utilisateur, mot_de_passe)
            de = formataddr((expediteur_nom or "ÉchéancePro", expediteur_adresse or utilisateur))
        else:
            conn, de = get_connection(), settings.DEFAULT_FROM_EMAIL
        EmailMessage(
            "ÉchéancePro — e-mail de test",
            "Ceci est un e-mail de test envoyé depuis ÉchéancePro.\nSi vous le lisez, l'envoi des alertes fonctionne.",
            de, [destinataire], connection=conn,
        ).send()
    except Exception as exc:  # erreur réseau, authentification, certificat…
        return False, f"{type(exc).__name__} : {exc}"
    return True, f"E-mail de test envoyé à {destinataire}."
