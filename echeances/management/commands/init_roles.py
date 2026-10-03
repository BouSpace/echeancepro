from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from echeances.permissions import permissions_de

# Rôles de départ. Une fois créés, ils se modifient depuis la page « Rôles » de l'application.
ROLES = {
    "Gestionnaire": [
        "echeances.view_echeance", "echeances.add_echeance", "echeances.change_echeance",
        "echeances.cloturer_echeance", "echeances.importer_echeance", "echeances.exporter_echeance",
        "echeances.voir_approvisionnement",
        "echeances.view_banque",
        "echeances.view_fournisseur", "echeances.add_fournisseur", "echeances.change_fournisseur",
        "echeances.view_periode", "echeances.add_periode", "echeances.change_periode", "echeances.delete_periode",
    ],
    "Valideur": [
        "echeances.view_echeance", "echeances.cloturer_echeance", "echeances.exporter_echeance",
        "echeances.voir_approvisionnement", "echeances.view_banque", "echeances.view_fournisseur",
    ],
    "Lecteur": [
        "echeances.view_echeance", "echeances.exporter_echeance", "echeances.voir_approvisionnement",
        "echeances.view_banque", "echeances.view_fournisseur",
    ],
}


class Command(BaseCommand):
    help = (
        "Crée les rôles de départ (Gestionnaire, Valideur, Lecteur) s'ils n'existent pas. "
        "Les rôles existants ne sont pas touchés, sauf avec --reinitialiser."
    )

    def add_arguments(self, parser):
        parser.add_argument("--reinitialiser", action="store_true",
                            help="Remet les droits d'origine sur les trois rôles de départ (écrase vos modifications).")

    def handle(self, *args, **options):
        for nom, codes in ROLES.items():
            groupe, cree = Group.objects.get_or_create(name=nom)
            if cree or options["reinitialiser"]:
                groupe.permissions.set(permissions_de(codes))
                self.stdout.write(f"  {nom} : {len(codes)} droit(s) {'créé' if cree else 'réinitialisé'}")
            else:
                self.stdout.write(f"  {nom} : conservé tel quel")
        self.stdout.write(self.style.SUCCESS("Rôles prêts. Les superutilisateurs ont tous les droits."))
