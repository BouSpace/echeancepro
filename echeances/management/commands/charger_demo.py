from datetime import date

from django.core.management.base import BaseCommand

from echeances.models import Banque, Echeance, Fournisseur

T = Echeance.Type
DONNEES = [
    # banque, type, fournisseur, création, échéance, montant
    ("CORIS", T.TRAITE, "SAHA ENERGY", date(2026, 7, 28), date(2026, 10, 27), 100_000_000),
    ("CORIS", T.TRAITE, "PRIME OIL", date(2026, 7, 28), date(2026, 10, 27), 100_000_000),
    ("CORIS", T.TRAITE, "SOCOGHAF", date(2026, 7, 28), date(2026, 10, 27), 100_000_000),
    ("CORIS", T.TRAITE, "STFME", date(2026, 7, 28), date(2026, 10, 27), 200_000_000),
    ("CORIS", T.TRAITE, "HAGE INDUSTRIES", date(2026, 6, 9), date(2026, 12, 8), 200_000_000),
    ("CORIS", T.TRAITE, "BIA", date(2026, 5, 22), date(2026, 6, 15), 100_000_000),
    ("CORIS", T.TRAITE, "CFAO MOBILITY", date(2026, 7, 28), date(2026, 10, 27), 157_926_221),
    ("CORIS", T.TRAITE, "ACCES OIL", date(2026, 9, 16), date(2026, 12, 15), 200_000_000),
    ("BSIC", T.TRAITE, "ITAOUA", date(2026, 8, 28), date(2027, 2, 27), 150_000_000),
    ("BSIC", T.TRAITE, "AFRICA BULDING AND FUTUR", date(2026, 8, 28), date(2027, 2, 27), 150_000_000),
    ("CORIS", T.CHEQUE, "CIM METAL", date(2026, 7, 7), date(2026, 8, 30), 102_841_397),
    ("CORIS", T.CHEQUE, "CIMBURKINA", date(2026, 10, 2), date(2026, 10, 12), 100_000_000),
    ("CORIS", T.CHEQUE, "CIMBURKINA", date(2026, 10, 2), date(2026, 10, 30), 100_000_000),
    ("CORIS", T.CHEQUE, "EPC BURKINA SARL", date(2026, 10, 1), date(2026, 10, 15), 25_000_000),
]


class Command(BaseCommand):
    help = "Charge les banques et échéances du fichier Excel d'origine (TEFA, octobre 2026) pour tester."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Supprime d'abord toutes les échéances.")

    def handle(self, *args, reset=False, **options):
        if reset:
            Echeance.objects.all().delete()
        banques = {
            "CORIS": Banque.objects.get_or_create(nom="CORIS BANK", defaults={"code": "CORIS"})[0],
            "BSIC": Banque.objects.get_or_create(nom="BSIC", defaults={"code": "BSIC"})[0],
        }
        Banque.objects.get_or_create(nom="VISTA BANK GAOUA-BATIE", defaults={"code": "VISTA"})
        nb = 0
        for b, t, f, dc, de, m in DONNEES:
            fournisseur, _ = Fournisseur.objects.get_or_create(nom=f)
            _, cree = Echeance.objects.get_or_create(
                banque=banques[b], type=t, fournisseur=fournisseur, date_echeance=de, montant=m,
                defaults={"date_creation": dc},
            )
            nb += cree
        self.stdout.write(self.style.SUCCESS(f"{nb} échéance(s) de démonstration créée(s)."))
