from django.core.management.base import BaseCommand

from echeances.notifications import envoyer_recap


class Command(BaseCommand):
    help = ("Envoie le récapitulatif quotidien des échéances (à planifier chaque matin, "
            "par exemple à 7 h 30, avec le Planificateur de tâches Windows ou cron).")

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="Renvoie même si le récapitulatif du jour a déjà été envoyé.")

    def handle(self, *args, force=False, **options):
        nb = envoyer_recap(force=force)
        self.stdout.write(self.style.SUCCESS(f"{nb} récapitulatif(s) envoyé(s)."))
