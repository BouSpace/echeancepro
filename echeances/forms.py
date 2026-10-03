from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.models import Group
from django.utils import timezone

from . import permissions as droits
from .models import Banque, Echeance, EvenementRole, Fournisseur, ParametresAlertes, Periode, Profil


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class EcheanceForm(forms.ModelForm):
    nouveau_fournisseur = forms.CharField(
        label="ou nouveau fournisseur", max_length=200, required=False,
        help_text="Saisissez un nom s'il n'est pas dans la liste.",
    )

    class Meta:
        model = Echeance
        fields = [
            "banque", "type", "fournisseur", "nouveau_fournisseur", "reference",
            "date_creation", "date_echeance", "montant", "cout_aval",
            "commentaire", "piece_jointe",
        ]
        widgets = {
            "date_creation": DateInput(),
            "date_echeance": DateInput(),
            "commentaire": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["banque"].queryset = Banque.objects.filter(actif=True)
        self.fields["fournisseur"].queryset = Fournisseur.objects.filter(actif=True)
        self.fields["fournisseur"].required = False
        if not self.instance.pk and not self.initial.get("date_creation"):
            self.initial["date_creation"] = timezone.localdate()

    def clean(self):
        data = super().clean()
        nouveau = (data.get("nouveau_fournisseur") or "").strip()
        if not data.get("fournisseur") and not nouveau:
            self.add_error("fournisseur", "Choisissez un fournisseur ou saisissez-en un nouveau.")
        dc, de = data.get("date_creation"), data.get("date_echeance")
        if dc and de and de < dc:
            self.add_error("date_echeance", "La date d'échéance doit être postérieure à la date de création.")
        if data.get("montant") is not None and data["montant"] <= 0:
            self.add_error("montant", "Le montant doit être positif.")
        if data.get("type") != Echeance.Type.TRAITE and data.get("cout_aval"):
            self.add_error("cout_aval", "Le coût d'aval ne concerne que les traites.")
        return data

    def save(self, commit=True):
        nouveau = (self.cleaned_data.get("nouveau_fournisseur") or "").strip()
        if nouveau:
            self.instance.fournisseur, _ = Fournisseur.objects.get_or_create(
                nom__iexact=nouveau, defaults={"nom": nouveau.upper()}
            )
        return super().save(commit)


class ClotureForm(forms.Form):
    CHOIX = [
        (Echeance.Statut.PAYEE, "Payée — le chèque ou la traite est passé"),
        (Echeance.Statut.IMPAYEE, "Impayée — rejeté à l'échéance"),
        (Echeance.Statut.RENOUVELEE, "Renouvelée — remplacée par une nouvelle traite"),
        (Echeance.Statut.ANNULEE, "Annulée — saisie par erreur ou opération annulée"),
    ]
    statut = forms.ChoiceField(label="Résultat", choices=CHOIX, widget=forms.RadioSelect)
    date_cloture = forms.DateField(label="Date", widget=DateInput())
    reference = forms.CharField(label="Référence ou motif", max_length=200, required=False)

    def clean(self):
        data = super().clean()
        if data.get("statut") == Echeance.Statut.IMPAYEE and not data.get("reference"):
            self.add_error("reference", "Indiquez le motif du rejet.")
        return data


class _PeriodeField(forms.ChoiceField):
    """Choix tirés de la table des périodes ; accepte aussi tout nombre de jours (liens du tableau de bord)."""

    def valid_value(self, value):
        return value == "retard" or (value.isdigit() and int(value) > 0) or super().valid_value(value)


class FiltreForm(forms.Form):
    q = forms.CharField(label="Recherche", required=False)
    banque = forms.ModelChoiceField(label="Banque", queryset=Banque.objects.all(), required=False, empty_label="Toutes")
    type = forms.ChoiceField(label="Type", choices=[("", "Tous")] + list(Echeance.Type.choices), required=False)
    statut = forms.ChoiceField(
        label="Statut", choices=[("", "Tous"), ("ouvertes", "Ouvertes")] + list(Echeance.Statut.choices), required=False
    )
    periode = _PeriodeField(label="Période", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choix = [("", "Toutes les dates"), ("retard", "En retard")]
        choix += [(str(p.jours), p.libelle) for p in Periode.objects.filter(actif=True)]
        self.fields["periode"].choices = choix


class ImportForm(forms.Form):
    fichier = forms.FileField(label="Fichier Excel (.xlsx)")


class UtilisateurForm(forms.ModelForm):
    """Création d'un utilisateur avec son rôle (groupe) et son mot de passe initial."""

    roles = forms.ModelMultipleChoiceField(
        label="rôles", queryset=Group.objects.order_by("name"), required=False, widget=forms.CheckboxSelectMultiple,
        help_text="Les droits des rôles cochés s'additionnent. Sans rôle, l'utilisateur n'accède qu'à son profil.",
    )
    photo = forms.ImageField(label="photo", required=False, help_text="Image JPG ou PNG, facultative.")
    password1 = forms.CharField(label="mot de passe", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="confirmer le mot de passe", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    class Meta:
        model = get_user_model()
        fields = ["username", "first_name", "last_name", "email"]

    def __init__(self, *args, editeur=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.fields["username"].help_text = "Identifiant de connexion."
        self.fields["roles"].queryset = droits.roles_assignables(editeur)
        self.order_fields(["username", "first_name", "last_name", "email", "roles", "photo", "password1", "password2"])

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2:
            if p1 != p2:
                self.add_error("password2", "Les deux mots de passe ne sont pas identiques.")
            else:
                try:
                    password_validation.validate_password(p1, self.instance)
                except forms.ValidationError as exc:
                    self.add_error("password1", exc)
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
            user.groups.set(self.cleaned_data["roles"])
            if self.cleaned_data.get("photo"):
                Profil.objects.update_or_create(user=user, defaults={"photo": self.cleaned_data["photo"]})
        return user


class FiltreUtilisateurForm(forms.Form):
    q = forms.CharField(label="Recherche", required=False, widget=forms.TextInput(attrs={"placeholder": "Identifiant, nom ou e-mail"}))
    role = forms.ModelChoiceField(label="Rôle", queryset=Group.objects.order_by("name"), required=False, empty_label="Tous les rôles")
    statut = forms.ChoiceField(
        label="Statut", required=False,
        choices=[("", "Tous"), ("actif", "Actifs"), ("inactif", "Désactivés")],
    )


class BanqueForm(forms.ModelForm):
    class Meta:
        model = Banque
        fields = ["nom", "numero_compte", "code", "actif"]


class FournisseurForm(forms.ModelForm):
    class Meta:
        model = Fournisseur
        fields = ["nom", "telephone", "email", "actif"]


class ProfilForm(forms.ModelForm):
    photo = forms.ImageField(label="photo", required=False)

    class Meta:
        model = get_user_model()
        fields = ["first_name", "last_name", "email"]

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit and self.cleaned_data.get("photo"):
            Profil.objects.update_or_create(user=user, defaults={"photo": self.cleaned_data["photo"]})
        return user


class UtilisateurModifierForm(forms.ModelForm):
    """Modification d'un utilisateur existant (le mot de passe se change depuis son propre profil)."""

    roles = forms.ModelMultipleChoiceField(
        label="rôles", queryset=Group.objects.order_by("name"), required=False, widget=forms.CheckboxSelectMultiple,
        help_text="Les droits des rôles cochés s'additionnent.",
    )
    photo = forms.ImageField(label="photo", required=False)

    class Meta:
        model = get_user_model()
        fields = ["first_name", "last_name", "email", "is_active"]
        labels = {"is_active": "compte actif"}

    def __init__(self, *args, editeur=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.editeur = editeur
        self.fields["roles"].queryset = (
            droits.roles_assignables(editeur) | self.instance.groups.all()  # garder les rôles déjà portés
        ).distinct().order_by("name")
        self.fields["roles"].initial = list(self.instance.groups.values_list("pk", flat=True))
        self.order_fields(["first_name", "last_name", "email", "roles", "photo", "is_active"])

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            user.groups.set(self.cleaned_data["roles"])
            if self.cleaned_data.get("photo"):
                Profil.objects.update_or_create(user=user, defaults={"photo": self.cleaned_data["photo"]})
        return user


class PeriodeForm(forms.ModelForm):
    class Meta:
        model = Periode
        fields = ["libelle", "jours", "tableau_de_bord", "actif"]

    def clean(self):
        data = super().clean()
        if data.get("tableau_de_bord") and data.get("actif"):
            autres = Periode.objects.filter(tableau_de_bord=True, actif=True).exclude(pk=self.instance.pk)
            if autres.count() >= Periode.MAX_TABLEAU_DE_BORD:
                self.add_error(
                    "tableau_de_bord",
                    f"Le tableau de bord affiche {Periode.MAX_TABLEAU_DE_BORD} périodes au plus : "
                    "décochez-en une autre d'abord.",
                )
        return data


class FiltreAuditForm(forms.Form):
    OBJETS = [("", "Tous"), ("echeance", "Échéances"), ("banque", "Banques"),
              ("fournisseur", "Fournisseurs"), ("periode", "Périodes"), ("role", "Rôles"), ("parametres", "Alertes e-mail")]
    ACTIONS = [("", "Toutes"), ("+", "Créations"), ("~", "Modifications"), ("-", "Suppressions")]

    objet = forms.ChoiceField(label="Objet", choices=OBJETS, required=False)
    action = forms.ChoiceField(label="Action", choices=ACTIONS, required=False)
    utilisateur = forms.ModelChoiceField(
        label="Utilisateur", queryset=get_user_model().objects.order_by("username"), required=False, empty_label="Tous",
    )
    du = forms.DateField(label="Du", required=False, widget=DateInput())
    au = forms.DateField(label="Au", required=False, widget=DateInput())


class RoleForm(forms.ModelForm):
    """Un rôle = un nom + une grille de droits (cases à cocher, regroupées par module)."""

    class Meta:
        model = Group
        fields = ["name"]
        labels = {"name": "Nom du rôle"}

    def __init__(self, *args, editeur=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.editeur = editeur
        actuels = droits.codes_du_role(self.instance) if self.instance.pk else set()
        self.noms = {}
        for code, libelle in droits.LIBELLES.items():
            nom = "droit_" + code.replace(".", "__")
            self.noms[code] = nom
            self.fields[nom] = forms.BooleanField(label=libelle, required=False, initial=code in actuels)

    @property
    def sections(self):
        """[(titre du module, [champs])] pour l'affichage en cartes."""
        return [(titre, [self[self.noms[code]] for code, _ in items]) for titre, items in droits.CATALOGUE]

    def codes_coches(self):
        return {code for code, nom in self.noms.items() if self.cleaned_data.get(nom)}

    def clean(self):
        data = super().clean()
        coches = self.codes_coches()
        if not coches:
            self.add_error(None, "Cochez au moins un droit.")
        editeur = self.editeur
        if editeur is not None and not editeur.is_superuser:
            en_trop = [droits.LIBELLES[c] for c in coches if not editeur.has_perm(c)]
            if en_trop:
                self.add_error(None, "Vous ne pouvez pas accorder des droits que vous n'avez pas : " + " ; ".join(en_trop) + ".")
            if self.instance.pk and self.instance.user_set.filter(pk=editeur.pk).exists():
                if not {"auth.view_group", "auth.change_group"} <= coches:
                    self.add_error(None, "Vous ne pouvez pas retirer à votre propre rôle la gestion des rôles.")
        return data

    def save(self, commit=True):
        creation = self.instance.pk is None
        avant = set() if creation else droits.codes_du_role(self.instance)
        groupe = super().save()
        coches = self.codes_coches()
        groupe.permissions.set(droits.permissions_de(sorted(coches)))
        lignes = [f"Ajouté : {droits.LIBELLES[c]}" for c in droits.CODES if c in coches - avant]
        lignes += [f"Retiré : {droits.LIBELLES[c]}" for c in droits.CODES if c in avant - coches]
        if creation or lignes or "name" in self.changed_data:
            if "name" in self.changed_data and not creation:
                lignes.insert(0, f"Nom : {self.initial.get('name')} → {groupe.name}")
            EvenementRole.objects.create(
                utilisateur=self.editeur, action="+" if creation else "~", nom=groupe.name, detail="\n".join(lignes),
            )
        return groupe


class ParametresAlertesForm(forms.ModelForm):
    mot_de_passe = forms.CharField(
        label="mot de passe", required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text="Laissez vide pour conserver le mot de passe enregistré. Il est stocké chiffré et jamais réaffiché.",
    )

    class Meta:
        model = ParametresAlertes
        fields = ["utiliser", "hote", "port", "securite", "utilisateur", "mot_de_passe",
                  "expediteur_nom", "expediteur_adresse", "paliers"]

    def clean_paliers(self):
        brut = self.cleaned_data["paliers"]
        try:
            jours = sorted({int(x) for x in brut.split(",") if x.strip()}, reverse=True)
        except ValueError:
            raise forms.ValidationError("Saisissez des nombres de jours séparés par des virgules, ex. : 15,7,3.")
        if not jours or min(jours) < 1 or len(jours) > 6:
            raise forms.ValidationError("Indiquez entre 1 et 6 paliers, chacun d'au moins 1 jour.")
        return ",".join(str(j) for j in jours)

    def clean(self):
        data = super().clean()
        if data.get("utiliser"):
            if not data.get("hote"):
                self.add_error("hote", "Indiquez le serveur SMTP pour utiliser ces réglages.")
            if not data.get("expediteur_adresse"):
                self.add_error("expediteur_adresse", "Indiquez l'adresse de l'expéditeur.")
        return data

    def save(self, commit=True):
        from django.utils import timezone
        from .mail import chiffrer

        p = super().save(commit=False)
        nouveau = self.cleaned_data.get("mot_de_passe")
        if nouveau:
            p.mot_de_passe_chiffre = chiffrer(nouveau)
            p.mot_de_passe_maj = timezone.now()
        if commit:
            p.save()
        return p
