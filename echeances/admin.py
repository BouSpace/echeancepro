from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Banque, Echeance, EnvoiRecap, Fournisseur, Periode, SmsEnvoye


@admin.register(Periode)
class PeriodeAdmin(admin.ModelAdmin):
    list_display = ("libelle", "jours", "tableau_de_bord", "actif")


@admin.register(Banque)
class BanqueAdmin(admin.ModelAdmin):
    list_display = ("nom", "code", "actif")
    list_filter = ("actif",)
    search_fields = ("nom", "code")


@admin.register(Fournisseur)
class FournisseurAdmin(admin.ModelAdmin):
    list_display = ("nom", "telephone", "email", "actif")
    list_filter = ("actif",)
    search_fields = ("nom",)


@admin.register(Echeance)
class EcheanceAdmin(SimpleHistoryAdmin):
    list_display = ("date_echeance", "banque", "type", "fournisseur", "montant", "cout_aval", "statut")
    list_filter = ("statut", "type", "banque")
    search_fields = ("fournisseur__nom", "reference", "commentaire")
    date_hierarchy = "date_echeance"
    autocomplete_fields = ("fournisseur",)


@admin.register(EnvoiRecap)
class EnvoiRecapAdmin(admin.ModelAdmin):
    list_display = ("date", "destinataire", "canal", "nb_echeances", "envoye_le")
    list_filter = ("canal",)


@admin.register(SmsEnvoye)
class SmsEnvoyeAdmin(admin.ModelAdmin):
    list_display = ("envoye_le", "numero", "texte")
