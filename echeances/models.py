from datetime import date

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from simple_history.models import HistoricalRecords


class Banque(models.Model):
    nom = models.CharField("nom", max_length=100, unique=True)
    code = models.CharField("code court", max_length=20, blank=True, help_text="Ex. : CORIS, BSIC")
    numero_compte = models.CharField("numéro de compte", max_length=50, unique=True, null=True, blank=True)
    actif = models.BooleanField("active", default=True)
    history = HistoricalRecords(verbose_name="historique")

    class Meta:
        ordering = ["nom"]
        verbose_name = "banque"

    def __str__(self):
        return self.code or self.nom


class Fournisseur(models.Model):
    nom = models.CharField("nom", max_length=200, unique=True)
    telephone = models.CharField("téléphone", max_length=30, blank=True)
    email = models.EmailField("e-mail", blank=True)
    actif = models.BooleanField("actif", default=True)
    history = HistoricalRecords(verbose_name="historique")

    class Meta:
        ordering = ["nom"]
        verbose_name = "fournisseur"

    def __str__(self):
        return self.nom


class Periode(models.Model):
    """Fenêtre « les N prochains jours », utilisée par le filtre des échéances et le tableau de bord."""

    MAX_TABLEAU_DE_BORD = 4

    libelle = models.CharField("libellé", max_length=60, help_text="Ex. : 15 prochains jours, 6 prochains mois")
    jours = models.PositiveIntegerField("nombre de jours", unique=True, validators=[MinValueValidator(1)])
    tableau_de_bord = models.BooleanField(
        "afficher sur le tableau de bord", default=False,
        help_text=f"Maximum {MAX_TABLEAU_DE_BORD} périodes sur le tableau de bord.",
    )
    actif = models.BooleanField("active", default=True)
    history = HistoricalRecords(verbose_name="historique")

    class Meta:
        ordering = ["jours"]
        verbose_name = "période"

    def __str__(self):
        return self.libelle


class EcheanceQuerySet(models.QuerySet):
    def ouvertes(self):
        """Échéances non encore clôturées (ni payées, ni impayées, ni renouvelées, ni annulées)."""
        return self.filter(statut=Echeance.Statut.A_VENIR)

    def en_retard(self, jour=None):
        jour = jour or timezone.localdate()
        return self.ouvertes().filter(date_echeance__lt=jour)

    def entre(self, debut, fin):
        return self.filter(date_echeance__gte=debut, date_echeance__lte=fin)

    def total(self):
        agg = self.aggregate(m=models.Sum("montant"), c=models.Sum("cout_aval"))
        return (agg["m"] or 0) + (agg["c"] or 0)


class Echeance(models.Model):
    class Type(models.TextChoices):
        CHEQUE = "CHEQUE", "Chèque"
        TRAITE = "TRAITE", "Traite"

    class Statut(models.TextChoices):
        A_VENIR = "A_VENIR", "À venir"
        PAYEE = "PAYEE", "Payée"
        IMPAYEE = "IMPAYEE", "Impayée"
        RENOUVELEE = "RENOUVELEE", "Renouvelée"
        ANNULEE = "ANNULEE", "Annulée"

    STATUTS_CLOTURE = [Statut.PAYEE, Statut.IMPAYEE, Statut.RENOUVELEE, Statut.ANNULEE]

    banque = models.ForeignKey(Banque, on_delete=models.PROTECT, related_name="echeances", verbose_name="banque")
    type = models.CharField("type", max_length=20, choices=Type.choices)
    fournisseur = models.ForeignKey(
        Fournisseur, on_delete=models.PROTECT, related_name="echeances", verbose_name="fournisseur / bénéficiaire"
    )
    reference = models.CharField("n° de chèque ou de traite", max_length=50, blank=True)
    date_creation = models.DateField("date de création")
    date_echeance = models.DateField("date d'échéance", db_index=True)
    montant = models.DecimalField("montant (F CFA)", max_digits=15, decimal_places=0)
    cout_aval = models.DecimalField(
        "coût d'aval et frais (F CFA)", max_digits=15, decimal_places=0, default=0,
        help_text="Uniquement pour les traites (aval, frais bancaires).",
    )
    commentaire = models.TextField("commentaire", blank=True)
    piece_jointe = models.FileField("pièce jointe", upload_to="pieces/%Y/%m/", blank=True)

    statut = models.CharField("statut", max_length=20, choices=Statut.choices, default=Statut.A_VENIR, db_index=True)
    date_cloture = models.DateField("date de clôture", null=True, blank=True)
    reference_cloture = models.CharField("référence (avis bancaire, motif de rejet…)", max_length=200, blank=True)
    renouvelee_par = models.OneToOneField(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="renouvelle", verbose_name="renouvelée par",
    )

    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="créée par",
    )
    cree_le = models.DateTimeField("créée le", auto_now_add=True)
    modifie_le = models.DateTimeField("modifiée le", auto_now=True)

    history = HistoricalRecords(verbose_name="historique")
    objects = EcheanceQuerySet.as_manager()

    class Meta:
        ordering = ["date_echeance", "banque__nom"]
        verbose_name = "échéance"
        permissions = [
            ("cloturer_echeance", "Peut clôturer une échéance (payée, impayée, renouvelée)"),
            ("importer_echeance", "Peut importer des échéances depuis Excel"),
            ("exporter_echeance", "Peut exporter la liste des échéances en Excel"),
            ("voir_approvisionnement", "Peut consulter les montants à approvisionner"),
        ]

    def __str__(self):
        return f"{self.get_type_display()} {self.fournisseur} — {self.date_echeance:%d/%m/%Y}"

    def get_absolute_url(self):
        return reverse("echeance_detail", args=[self.pk])

    @property
    def montant_total(self):
        return (self.montant or 0) + (self.cout_aval or 0)

    @property
    def est_ouverte(self):
        return self.statut == self.Statut.A_VENIR

    @property
    def jours_restants(self):
        return (self.date_echeance - date.today()).days

    @property
    def en_retard(self):
        return self.est_ouverte and self.jours_restants < 0

    @property
    def urgence(self):
        """Niveau d'urgence pour l'affichage : retard, aujourdhui, urgent, proche, normal, close."""
        if not self.est_ouverte:
            return "close"
        j = self.jours_restants
        if j < 0:
            return "retard"
        if j == 0:
            return "aujourdhui"
        if j <= 3:
            return "urgent"
        if j <= 7:
            return "proche"
        return "normal"

    def cloturer(self, statut, date_cloture=None, reference="", user=None):
        self.statut = statut
        self.date_cloture = date_cloture or timezone.localdate()
        self.reference_cloture = reference
        if user is not None:
            self._history_user = user
        self.save()


class Profil(models.Model):
    """Informations complémentaires d'un utilisateur (photo affichée dans le menu du haut)."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profil")
    photo = models.ImageField("photo", upload_to="photos/", blank=True)

    class Meta:
        verbose_name = "profil"

    def __str__(self):
        return f"Profil de {self.user}"


class EvenementRole(models.Model):
    """Trace des créations, modifications et suppressions de rôles (groupes de permissions)."""

    ACTIONS = [("+", "Création"), ("~", "Modification"), ("-", "Suppression")]

    date = models.DateTimeField(auto_now_add=True)
    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    action = models.CharField(max_length=1, choices=ACTIONS)
    nom = models.CharField("rôle", max_length=150)
    detail = models.TextField(blank=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "événement de rôle"
        verbose_name_plural = "événements de rôles"

    def __str__(self):
        return f"{self.get_action_display()} du rôle {self.nom}"


class Entreprise(models.Model):
    """Identité de l'entreprise (une seule ligne) : affichée dans l'en-tête des documents imprimés."""

    nom = models.CharField("raison sociale", max_length=200, blank=True)
    logo = models.ImageField("logo", upload_to="entreprise/", blank=True)
    adresse = models.TextField("adresse", blank=True)
    telephone = models.CharField("téléphone", max_length=60, blank=True)
    email = models.EmailField("e-mail", blank=True)

    history = HistoricalRecords(verbose_name="historique")

    class Meta:
        verbose_name = "entreprise"
        verbose_name_plural = "entreprise"

    def __str__(self):
        return self.nom or "Entreprise"

    @classmethod
    def charger(cls):
        return cls.objects.get_or_create(pk=1)[0]


class ParametresAlertes(models.Model):
    """Réglages d'envoi des alertes (une seule ligne) : serveur e-mail et paliers d'alerte."""

    SECURITES = [("tls", "STARTTLS (port 587)"), ("ssl", "SSL/TLS (port 465)"), ("aucune", "Aucun (déconseillé)")]

    utiliser = models.BooleanField(
        "utiliser ces réglages", default=False,
        help_text="Décoché, le logiciel utilise les réglages e-mail du serveur (fichier .env).",
    )
    hote = models.CharField("serveur SMTP", max_length=200, blank=True, help_text="Ex. : smtp.votre-domaine.com")
    port = models.PositiveIntegerField("port", default=587)
    securite = models.CharField("chiffrement", max_length=10, choices=SECURITES, default="tls")
    utilisateur = models.CharField("identifiant", max_length=200, blank=True)
    mot_de_passe_chiffre = models.TextField(blank=True)
    mot_de_passe_maj = models.DateTimeField("mot de passe mis à jour le", null=True, blank=True)
    expediteur_nom = models.CharField("nom de l'expéditeur", max_length=100, default="ÉchéancePro")
    expediteur_adresse = models.EmailField("adresse de l'expéditeur", blank=True)
    paliers = models.CharField(
        "paliers d'alerte (jours avant l'échéance)", max_length=60, default="15,7,3",
        help_text="Jours séparés par des virgules, ex. : 15,7,3. Les échéances du jour et en retard sont toujours signalées.",
    )

    history = HistoricalRecords(excluded_fields=["mot_de_passe_chiffre"], verbose_name="historique")

    class Meta:
        verbose_name = "paramètres d'alertes"
        verbose_name_plural = "paramètres d'alertes"
        permissions = [("gerer_parametres_alertes", "Peut gérer les paramètres e-mail et les alertes")]

    def __str__(self):
        return "Paramètres d'alertes"

    @classmethod
    def charger(cls):
        return cls.objects.get_or_create(pk=1)[0]

    @property
    def utilisable(self):
        return self.utiliser and bool(self.hote) and bool(self.expediteur_adresse)

    def mot_de_passe(self):
        from .mail import dechiffrer
        return dechiffrer(self.mot_de_passe_chiffre)

    @property
    def mot_de_passe_illisible(self):
        return bool(self.mot_de_passe_chiffre) and self.mot_de_passe() is None

    def liste_paliers(self):
        try:
            jours = {int(x) for x in self.paliers.split(",") if x.strip()}
        except ValueError:
            jours = set()
        return sorted((j for j in jours if j > 0), reverse=True) or [15, 7, 3]


class EnvoiRecap(models.Model):
    """Trace des récapitulatifs envoyés, pour ne jamais envoyer deux fois le même jour."""

    date = models.DateField()
    destinataire = models.EmailField()
    canal = models.CharField(max_length=20, default="email")
    envoye_le = models.DateTimeField(auto_now_add=True)
    nb_echeances = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("date", "destinataire", "canal")]
        ordering = ["-envoye_le"]
        verbose_name = "envoi d'alerte"
        verbose_name_plural = "envois d'alertes"

    def __str__(self):
        return f"{self.date:%d/%m/%Y} → {self.destinataire} ({self.canal})"


class SmsEnvoye(models.Model):
    """Trace des SMS / WhatsApp envoyés, pour respecter le plafond mensuel."""

    numero = models.CharField(max_length=30)
    texte = models.CharField(max_length=500)
    envoye_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-envoye_le"]
        verbose_name = "SMS envoyé"
        verbose_name_plural = "SMS envoyés"

    def __str__(self):
        return f"{self.envoye_le:%d/%m/%Y %H:%M} → {self.numero}"
