from datetime import timedelta
from io import BytesIO

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import excel
from . import mail as mail_app
from .models import Banque, Echeance, Fournisseur, ParametresAlertes
from .notifications import envoyer_recap


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", verbosity=0)
        cls.today = timezone.localdate()
        cls.banque = Banque.objects.create(nom="CORIS BANK", code="CORIS")
        cls.fournisseur = Fournisseur.objects.create(nom="SAHA ENERGY")
        cls.gest = User.objects.create_user("gest", "gest@ex.com", "motdepasse-123")
        cls.gest.groups.add(Group.objects.get(name="Gestionnaire"))
        cls.lecteur = User.objects.create_user("lect", "lect@ex.com", "motdepasse-123")
        cls.lecteur.groups.add(Group.objects.get(name="Lecteur"))

    def creer(self, jours, type=Echeance.Type.CHEQUE, montant=100_000_000, cout=0):
        return Echeance.objects.create(
            banque=self.banque, fournisseur=self.fournisseur, type=type,
            date_creation=self.today - timedelta(days=30), date_echeance=self.today + timedelta(days=jours),
            montant=montant, cout_aval=cout,
        )


class ModeleTests(Base):
    def test_total_et_retard(self):
        e = self.creer(-2, Echeance.Type.TRAITE, 100, 5)
        self.assertEqual(e.montant_total, 105)
        self.assertTrue(e.en_retard)
        self.assertEqual(e.urgence, "retard")
        e.cloturer(Echeance.Statut.PAYEE)
        self.assertFalse(e.en_retard)
        self.assertEqual(Echeance.objects.en_retard().count(), 0)


class VuesTests(Base):
    def test_pages_principales(self):
        self.creer(3)
        self.client.force_login(self.gest)
        for nom in ["tableau_de_bord", "liste", "approvisionnement", "importer", "echeance_creer"]:
            self.assertEqual(self.client.get(reverse(nom)).status_code, 200, nom)

    def test_lecteur_ne_peut_pas_creer(self):
        self.client.force_login(self.lecteur)
        self.assertEqual(self.client.get(reverse("echeance_creer")).status_code, 403)

    def test_cloture_impayee_exige_un_motif(self):
        e = self.creer(-1)
        self.client.force_login(self.gest)
        url = reverse("echeance_cloturer", args=[e.pk])
        self.client.post(url, {"statut": "IMPAYEE", "date_cloture": self.today})
        e.refresh_from_db()
        self.assertEqual(e.statut, Echeance.Statut.A_VENIR)
        self.client.post(url, {"statut": "IMPAYEE", "date_cloture": self.today, "reference": "Provision insuffisante"})
        e.refresh_from_db()
        self.assertEqual(e.statut, Echeance.Statut.IMPAYEE)

    def test_renouvellement(self):
        e = self.creer(0, Echeance.Type.TRAITE)
        self.client.force_login(self.gest)
        url = reverse("echeance_creer") + f"?renouvelle={e.pk}"
        self.client.post(url, {
            "banque": self.banque.pk, "type": "TRAITE", "fournisseur": self.fournisseur.pk,
            "date_creation": self.today, "date_echeance": self.today + timedelta(days=90),
            "montant": 100_000_000, "cout_aval": 0,
        })
        e.refresh_from_db()
        self.assertEqual(e.statut, Echeance.Statut.RENOUVELEE)
        self.assertIsNotNone(e.renouvelee_par)


class ImportTests(Base):
    def test_import_modele(self):
        buf = BytesIO()
        excel.modele_vierge().save(buf)
        self.client.force_login(self.gest)
        f = SimpleUploadedFile("m.xlsx", buf.getvalue())
        self.client.post(reverse("importer"), {"fichier": f})
        self.assertEqual(Echeance.objects.count(), 1)


class AlertesTests(Base):
    def test_recap_envoye_une_fois_par_jour(self):
        self.creer(7)
        self.creer(-1)
        self.assertEqual(envoyer_recap(), 1)  # seul le gestionnaire reçoit (le lecteur non)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("1 en retard", mail.outbox[0].subject)
        self.assertEqual(envoyer_recap(), 0)


class ParametresAlertesTests(Base):
    def test_mot_de_passe_chiffre_et_relu(self):
        p = ParametresAlertes.charger()
        p.mot_de_passe_chiffre = mail_app.chiffrer("secret-smtp")
        self.assertNotIn("secret-smtp", p.mot_de_passe_chiffre)
        self.assertEqual(p.mot_de_passe(), "secret-smtp")

    def test_paliers_personnalises(self):
        ParametresAlertes.objects.update_or_create(pk=1, defaults={"paliers": "30,10"})
        self.creer(30)
        self.creer(10)
        self.creer(7)  # plus un palier : ne doit pas être signalé
        ctx = __import__("echeances.notifications", fromlist=["x"]).construire_recap()
        self.assertEqual([p["jours"] for p in ctx["paliers"]], [30, 10])

    def test_reglages_smtp_utilises_si_actives(self):
        p = ParametresAlertes.charger()
        p.utiliser, p.hote, p.expediteur_adresse = True, "smtp.exemple.test", "alertes@exemple.test"
        p.save()
        self.assertEqual(mail_app.connexion().host, "smtp.exemple.test")
        self.assertIn("alertes@exemple.test", mail_app.expediteur())

    def test_page_reservee_et_mot_de_passe_jamais_affiche(self):
        self.client.force_login(self.gest)
        self.assertEqual(self.client.get(reverse("parametres_alertes")).status_code, 403)
        admin = User.objects.create_superuser("adm", "adm@ex.com", "motdepasse-123")
        self.client.force_login(admin)
        self.client.post(reverse("parametres_alertes"), {
            "action": "enregistrer", "utiliser": "on", "hote": "smtp.exemple.test", "port": 587, "securite": "tls",
            "utilisateur": "u", "mot_de_passe": "tres-secret", "expediteur_nom": "X",
            "expediteur_adresse": "a@exemple.test", "paliers": "7,15",
        })
        p = ParametresAlertes.charger()
        self.assertEqual(p.mot_de_passe(), "tres-secret")
        self.assertEqual(p.paliers, "15,7")
        self.assertNotIn("tres-secret", self.client.get(reverse("parametres_alertes")).content.decode())

    def test_formulaire_refuse_hote_manquant(self):
        admin = User.objects.create_superuser("adm", "adm@ex.com", "motdepasse-123")
        self.client.force_login(admin)
        r = self.client.post(reverse("parametres_alertes"), {
            "action": "enregistrer", "utiliser": "on", "hote": "", "port": 587, "securite": "tls",
            "expediteur_nom": "X", "expediteur_adresse": "", "paliers": "15,7,3",
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(ParametresAlertes.charger().utiliser)
