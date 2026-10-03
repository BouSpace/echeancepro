"""Catalogue des droits proposés dans la grille d'un rôle.

Chaque droit est une permission Django (« app.codename »), regroupée par module avec un libellé clair.
Ajouter une ligne ici suffit pour qu'elle apparaisse dans le formulaire des rôles.
"""
from django.contrib.auth.models import Permission

CATALOGUE = [
    ("Échéances", [
        ("echeances.view_echeance", "Consulter les échéances et le tableau de bord"),
        ("echeances.add_echeance", "Créer une échéance"),
        ("echeances.change_echeance", "Modifier une échéance"),
        ("echeances.delete_echeance", "Supprimer une échéance"),
        ("echeances.cloturer_echeance", "Clôturer ou rouvrir une échéance (payée, impayée, renouvelée)"),
        ("echeances.importer_echeance", "Importer des échéances depuis Excel"),
        ("echeances.exporter_echeance", "Exporter la liste des échéances en Excel"),
    ]),
    ("Approvisionnement", [
        ("echeances.voir_approvisionnement", "Consulter les montants à approvisionner"),
    ]),
    ("Banques", [
        ("echeances.view_banque", "Consulter les banques"),
        ("echeances.add_banque", "Créer une banque"),
        ("echeances.change_banque", "Modifier une banque"),
        ("echeances.delete_banque", "Supprimer une banque"),
    ]),
    ("Fournisseurs", [
        ("echeances.view_fournisseur", "Consulter les fournisseurs"),
        ("echeances.add_fournisseur", "Créer un fournisseur"),
        ("echeances.change_fournisseur", "Modifier un fournisseur"),
        ("echeances.delete_fournisseur", "Supprimer un fournisseur"),
    ]),
    ("Périodes", [
        ("echeances.view_periode", "Consulter les périodes"),
        ("echeances.add_periode", "Créer une période"),
        ("echeances.change_periode", "Modifier une période"),
        ("echeances.delete_periode", "Supprimer une période"),
    ]),
    ("Utilisateurs", [
        ("auth.view_user", "Consulter les utilisateurs"),
        ("auth.add_user", "Créer un utilisateur"),
        ("auth.change_user", "Modifier un utilisateur"),
        ("auth.delete_user", "Supprimer un utilisateur"),
    ]),
    ("Rôles", [
        ("auth.view_group", "Consulter les rôles"),
        ("auth.add_group", "Créer un rôle"),
        ("auth.change_group", "Modifier un rôle"),
        ("auth.delete_group", "Supprimer un rôle"),
    ]),
    ("Audit", [
        ("echeances.view_historicalecheance", "Consulter le journal d'audit"),
    ]),
    ("Alertes", [
        ("echeances.gerer_parametres_alertes", "Gérer le serveur e-mail et les paliers d'alerte"),
    ]),
]

LIBELLES = {code: libelle for _, items in CATALOGUE for code, libelle in items}
CODES = list(LIBELLES)


def permissions_de(codes):
    """Objets Permission correspondant à une liste de « app.codename »."""
    trouvees = []
    for code in codes:
        app, nom = code.split(".")
        trouvees.append(Permission.objects.get(content_type__app_label=app, codename=nom))
    return trouvees


def codes_du_role(groupe):
    return {f"{p.content_type.app_label}.{p.codename}" for p in groupe.permissions.select_related("content_type")}


def roles_assignables(user):
    """Rôles qu'un utilisateur peut attribuer ou modifier : tous pour un superutilisateur,
    sinon seulement ceux dont les droits sont inclus dans les siens (pas d'élévation de privilèges)."""
    from django.contrib.auth.models import Group

    if user is None or user.is_superuser:
        return Group.objects.order_by("name")
    ids = [g.pk for g in Group.objects.all() if all(user.has_perm(c) for c in codes_du_role(g) & set(CODES))]
    return Group.objects.filter(pk__in=ids).order_by("name")
