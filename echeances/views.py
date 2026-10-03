from datetime import timedelta
from io import BytesIO

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Count, ProtectedError
from django.views.generic import CreateView, DeleteView, DetailView, UpdateView

from . import excel
from .forms import EntrepriseForm, FiltreAuditForm, ParametresAlertesForm, RoleForm, PeriodeForm, BanqueForm, ClotureForm, EcheanceForm, FournisseurForm, FiltreForm, ImportForm, FiltreUtilisateurForm, ProfilForm, UtilisateurModifierForm, UtilisateurForm
from .models import Banque, Echeance, Entreprise, EvenementRole, Fournisseur, ParametresAlertes, Periode


def _total(qs):
    agg = qs.aggregate(m=Sum("montant"), c=Sum("cout_aval"))
    return (agg["m"] or 0) + (agg["c"] or 0)


# --- Tableau de bord -----------------------------------------------------------

@login_required
def tableau_de_bord(request):
    if not request.user.has_perm("echeances.view_echeance"):
        return render(request, "echeances/accueil.html")
    today = timezone.localdate()
    ouvertes = Echeance.objects.ouvertes().select_related("banque", "fournisseur")

    retard = ouvertes.filter(date_echeance__lt=today)
    mois = ouvertes.entre(today, today + timedelta(days=30))
    periodes = list(Periode.objects.filter(actif=True, tableau_de_bord=True)[:Periode.MAX_TABLEAU_DE_BORD])
    tuiles = []
    for p in periodes:
        qs = ouvertes.entre(today, today + timedelta(days=p.jours))
        tuiles.append({"periode": p, "nb": qs.count(), "total": _total(qs)})

    # Les 30 prochains jours, regroupés par date d'échéance.
    jours = {}
    for e in mois:
        jours.setdefault(e.date_echeance, []).append(e)
    calendrier = [
        {"date": d, "echeances": lst, "total": sum(e.montant_total for e in lst),
         "delta": (d - today).days}
        for d, lst in sorted(jours.items())
    ]

    return render(request, "echeances/tableau_de_bord.html", {
        "today": today,
        "par_type": _par_type(ouvertes),
        "retard": retard,
        "total_retard": _total(retard),
        "tuiles": tuiles,
        "periodes": periodes,
        "calendrier": calendrier,
        "par_banque": _par_banque(ouvertes, today, [p.jours for p in periodes]),
    })


def _par_type(ouvertes):
    """Nombre, montant et part de chaque type (chèque, traite) parmi les échéances ouvertes."""
    lignes = []
    for valeur, libelle in Echeance.Type.choices:
        qs = ouvertes.filter(type=valeur)
        lignes.append({"type": valeur, "libelle": libelle, "nb": qs.count(), "total": _total(qs)})
    total = sum(l["total"] for l in lignes)
    for l in lignes:
        l["part"] = round(l["total"] * 100 / total) if total else 0
    return {"lignes": lignes, "nb": sum(l["nb"] for l in lignes), "total": total}


def _par_banque(ouvertes, today, horizons):
    lignes = []
    for b in Banque.objects.filter(actif=True):
        qs = ouvertes.filter(banque=b)
        valeurs = [_total(qs.entre(today, today + timedelta(days=h))) for h in horizons]
        retard = _total(qs.filter(date_echeance__lt=today))
        if any(valeurs) or retard:
            lignes.append({"banque": b, "retard": retard, "valeurs": valeurs})
    return lignes


# --- Montants à approvisionner ---------------------------------------------------

NB_MOIS_APPROVISIONNEMENT = 6


def _debut_mois(d, decalage=0):
    """Premier jour du mois situé `decalage` mois après celui de `d`."""
    n = d.year * 12 + d.month - 1 + decalage
    return d.replace(year=n // 12, month=n % 12 + 1, day=1)


def _periode_mois(debut, today):
    """Un mois à couvrir : le mois en cours ne compte qu'à partir d'aujourd'hui."""
    fin = _debut_mois(debut, 1) - timedelta(days=1)
    return {"debut": debut, "fin": fin, "du": max(debut, today)}


def _etat_approvisionnement(today):
    """Tableau banque × 6 mois (lignes, totaux) et chiffres clés de l'état."""
    mois = [_periode_mois(_debut_mois(today, i), today) for i in range(NB_MOIS_APPROVISIONNEMENT)]
    ouvertes = Echeance.objects.ouvertes()
    lignes = []
    for b in Banque.objects.filter(actif=True):
        qs = ouvertes.filter(banque=b)
        cellules = [_total(qs.entre(m["du"], m["fin"])) for m in mois]
        if any(cellules):
            lignes.append({"banque": b, "cellules": cellules, "total": sum(cellules)})
    totaux = [sum(l["cellules"][i] for l in lignes) for i in range(len(mois))]

    fenetre = ouvertes.filter(banque__actif=True).entre(mois[0]["du"], mois[-1]["fin"])
    par_type = []
    for valeur, libelle in Echeance.Type.choices:
        qs = fenetre.filter(type=valeur)
        par_type.append({"libelle": libelle, "nb": qs.count(), "total": _total(qs)})
    plus_charge = None
    if any(totaux):
        total_max, periode_max = max(zip(totaux, mois), key=lambda x: x[0])
        plus_charge = {"mois": periode_max["debut"], "total": total_max}
    return {
        "mois": mois, "lignes": lignes, "totaux": totaux,
        "total_general": sum(l["total"] for l in lignes),
        "total_retard": _total(ouvertes.filter(date_echeance__lt=today)),
        "nb_echeances": sum(t["nb"] for t in par_type), "par_type": par_type, "plus_charge": plus_charge,
        "periode_debut": mois[0]["du"], "periode_fin": mois[-1]["fin"],
    }


def _detail_mois(periode, banques=None):
    """Échéances ouvertes d'un mois, regroupées par banque, avec sous-totaux (banques : ids à retenir)."""
    qs = (Echeance.objects.ouvertes().entre(periode["du"], periode["fin"])
          .select_related("banque", "fournisseur").order_by("banque__nom", "date_echeance", "pk"))
    if banques:
        qs = qs.filter(banque_id__in=banques)
    groupes = {}
    for e in qs:
        g = groupes.setdefault(e.banque_id, {"banque": e.banque, "echeances": [], "total": 0})
        g["echeances"].append(e)
        g["total"] += e.montant_total
    liste = list(groupes.values())
    return {
        "periode": periode, "groupes": liste,
        "nb": sum(len(g["echeances"]) for g in liste), "total": sum(g["total"] for g in liste),
    }


def _contexte_document(today):
    """Éléments communs aux documents imprimés : identité de l'entreprise et référence."""
    return {"entreprise": Entreprise.charger(), "reference": f"AP-{today:%Y%m%d}", "today": today}


@login_required
@permission_required("echeances.voir_approvisionnement", raise_exception=True)
def approvisionnement(request):
    today = timezone.localdate()
    return render(request, "echeances/approvisionnement.html",
                  {**_etat_approvisionnement(today), **_contexte_document(today)})


@login_required
@permission_required("echeances.voir_approvisionnement", raise_exception=True)
def approvisionnement_mois(request, annee, mois):
    """Détail d'un mois (à imprimer pour accompagner l'état), filtrable par banque."""
    from datetime import date
    from django.http import Http404

    if not (1 <= mois <= 12 and 2000 <= annee <= 2100):
        raise Http404
    today = timezone.localdate()
    debut = date(annee, mois, 1)
    banque_id = request.GET.get("banque", "")
    banques = [int(banque_id)] if banque_id.isdigit() else None
    return render(request, "echeances/approvisionnement_mois.html", {
        **_contexte_document(today),
        "detail": _detail_mois(_periode_mois(debut, today), banques),
        "mois_precedent": _debut_mois(debut, -1), "mois_suivant": _debut_mois(debut, 1),
        "liste_banques": Banque.objects.filter(actif=True), "banque_id": banque_id,
        "annee": annee, "mois_num": mois,
    })


@login_required
@permission_required("echeances.voir_approvisionnement", raise_exception=True)
def approvisionnement_complet(request):
    """Édition complète : l'état, puis des annexes (un mois par annexe), au choix de l'utilisateur."""
    today = timezone.localdate()
    etat = _etat_approvisionnement(today)

    # Mois proposés en annexe : ceux qui comptent des échéances.
    disponibles, banques_par_id = [], {}
    for m in etat["mois"]:
        d = _detail_mois(m)
        if d["nb"]:
            disponibles.append({"cle": f"{m['debut']:%Y-%m}", "debut": m["debut"], "periode": m, "nb": d["nb"], "total": d["total"]})
            banques_par_id.update({g["banque"].pk: g["banque"] for g in d["groupes"]})
    banques = sorted(banques_par_id.values(), key=lambda b: b.nom)

    if request.GET.get("f"):  # formulaire envoyé : on respecte exactement les cases cochées
        cles = set(request.GET.getlist("mois"))
        ids = {int(x) for x in request.GET.getlist("banque") if x.isdigit()}
        inclure_etat = request.GET.get("etat") == "1"
    else:  # première ouverture : tout est coché
        cles = {m["cle"] for m in disponibles}
        ids = {b.pk for b in banques}
        inclure_etat = True

    annexes = []
    for m in disponibles:
        if m["cle"] in cles and ids:
            d = _detail_mois(m["periode"], ids)
            if d["nb"]:
                annexes.append({"numero": len(annexes) + 1, "detail": d})
    return render(request, "echeances/approvisionnement_complet.html", {
        **etat, **_contexte_document(today),
        "disponibles": disponibles, "banques": banques, "cles": cles, "ids": ids,
        "inclure_etat": inclure_etat, "annexes": annexes,
    })


# --- Liste et filtres ---------------------------------------------------------------

def _filtrer(request):
    form = FiltreForm(request.GET or None)
    qs = Echeance.objects.select_related("banque", "fournisseur")
    today = timezone.localdate()
    if form.is_valid():
        d = form.cleaned_data
        if d["q"]:
            qs = qs.filter(Q(fournisseur__nom__icontains=d["q"]) | Q(reference__icontains=d["q"])
                           | Q(commentaire__icontains=d["q"]))
        if d["banque"]:
            qs = qs.filter(banque=d["banque"])
        if d["type"]:
            qs = qs.filter(type=d["type"])
        if d["statut"] == "ouvertes":
            qs = qs.ouvertes()
        elif d["statut"]:
            qs = qs.filter(statut=d["statut"])
        if d["periode"] == "retard":
            qs = qs.en_retard(today)
        elif d["periode"]:
            qs = qs.entre(today, today + timedelta(days=int(d["periode"])))
    return form, qs


@login_required
@permission_required("echeances.view_echeance", raise_exception=True)
def liste(request):
    form, qs = _filtrer(request)
    return render(request, "echeances/liste.html", {
        "form": form, "echeances": qs, "total": _total(qs), "querystring": request.GET.urlencode(),
    })


@login_required
@permission_required("echeances.exporter_echeance", raise_exception=True)
def export_excel(request):
    _, qs = _filtrer(request)
    return _xlsx(excel.exporter(qs), f"echeances_{timezone.localdate():%Y%m%d}.xlsx")


def _xlsx(wb, nom):
    buf = BytesIO()
    wb.save(buf)
    resp = HttpResponse(buf.getvalue(),
                        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="{nom}"'
    return resp


# --- Création, modification, détail ----------------------------------------------------

class EcheanceCreate(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = Echeance
    form_class = EcheanceForm
    permission_required = "echeances.add_echeance"
    template_name = "echeances/form.html"

    def get_initial(self):
        initial = super().get_initial()
        origine_id = self.request.GET.get("renouvelle")
        if origine_id:
            o = get_object_or_404(Echeance, pk=origine_id)
            initial.update(banque=o.banque, type=o.type, fournisseur=o.fournisseur,
                           montant=o.montant, cout_aval=o.cout_aval,
                           commentaire=f"Renouvellement de l'échéance du {o.date_echeance:%d/%m/%Y}")
        return initial

    def form_valid(self, form):
        form.instance.cree_par = self.request.user
        resp = super().form_valid(form)
        origine_id = self.request.GET.get("renouvelle")
        if origine_id:
            o = Echeance.objects.filter(pk=origine_id, renouvelee_par__isnull=True).first()
            if o:
                o.renouvelee_par = self.object
                o.cloturer(Echeance.Statut.RENOUVELEE, user=self.request.user,
                           reference=f"Remplacée par l'échéance du {self.object.date_echeance:%d/%m/%Y}")
        messages.success(self.request, "Échéance enregistrée.")
        return resp

    def get_success_url(self):
        return reverse("liste")


class EcheanceUpdate(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = Echeance
    form_class = EcheanceForm
    permission_required = "echeances.change_echeance"
    template_name = "echeances/form.html"

    def form_valid(self, form):
        messages.success(self.request, "Modifications enregistrées.")
        return super().form_valid(form)


class EcheanceDetail(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Echeance
    permission_required = "echeances.view_echeance"
    raise_exception = True
    template_name = "echeances/detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["historique"] = self.object.history.select_related("history_user").order_by("-history_date")[:30]
        ctx["cloture_form"] = ClotureForm(initial={"date_cloture": timezone.localdate()})
        return ctx


@login_required
@permission_required("echeances.cloturer_echeance", raise_exception=True)
def cloturer(request, pk):
    e = get_object_or_404(Echeance, pk=pk)
    if not e.est_ouverte:
        messages.error(request, "Cette échéance est déjà clôturée.")
        return redirect(e)
    form = ClotureForm(request.POST or None, initial={"date_cloture": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        statut = form.cleaned_data["statut"]
        if statut == Echeance.Statut.RENOUVELEE:
            # La clôture se fera à l'enregistrement de la nouvelle traite.
            return redirect(f"{reverse('echeance_creer')}?renouvelle={e.pk}")
        e.cloturer(statut, form.cleaned_data["date_cloture"], form.cleaned_data["reference"], request.user)
        if statut == Echeance.Statut.IMPAYEE:
            from .notifications import alerter_impaye
            if alerter_impaye(e):
                messages.warning(request, "Échéance marquée impayée. Les valideurs ont été prévenus.")
            else:
                messages.warning(request, "Échéance marquée impayée, mais l'e-mail d'alerte n'a pas pu être envoyé "
                                          "(vérifiez les réglages e-mail).")
        else:
            messages.success(request, f"Échéance marquée « {e.get_statut_display().lower()} ».")
        return redirect(e)
    return render(request, "echeances/detail.html", {
        "object": e, "echeance": e, "cloture_form": form,
        "historique": e.history.select_related("history_user").order_by("-history_date")[:30],
    })


@login_required
@permission_required("echeances.cloturer_echeance", raise_exception=True)
def rouvrir(request, pk):
    e = get_object_or_404(Echeance, pk=pk)
    if request.method == "POST" and not e.est_ouverte and not e.renouvelee_par_id:
        e._history_user = request.user
        e.statut, e.date_cloture, e.reference_cloture = Echeance.Statut.A_VENIR, None, ""
        e.save()
        messages.info(request, "Échéance rouverte.")
    return redirect(e)


# --- Import -------------------------------------------------------------------

@login_required
@permission_required("echeances.importer_echeance", raise_exception=True)
def importer(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    erreurs = []
    if request.method == "POST" and form.is_valid():
        try:
            nb, erreurs = excel.importer(form.cleaned_data["fichier"], request.user)
        except Exception as exc:  # fichier illisible
            erreurs = [f"Le fichier n'a pas pu être lu : {exc}"]
            nb = 0
        if not erreurs:
            messages.success(request, f"{nb} échéance(s) importée(s).")
            return redirect("liste")
    return render(request, "echeances/import.html", {"form": form, "erreurs": erreurs})


@login_required
@permission_required("echeances.importer_echeance", raise_exception=True)
def modele_import(request):
    return _xlsx(excel.modele_vierge(), "modele_import_echeancepro.xlsx")


# --- Utilisateurs ---------------------------------------------------------------------

@login_required
@permission_required("auth.view_user", raise_exception=True)
def utilisateurs(request):
    form = FiltreUtilisateurForm(request.GET or None)
    users = get_user_model().objects.prefetch_related("groups").order_by("username")
    if form.is_valid():
        d = form.cleaned_data
        if d["q"]:
            users = users.filter(Q(username__icontains=d["q"]) | Q(first_name__icontains=d["q"])
                                 | Q(last_name__icontains=d["q"]) | Q(email__icontains=d["q"]))
        if d["role"]:
            users = users.filter(groups=d["role"])
        if d["statut"]:
            users = users.filter(is_active=d["statut"] == "actif")
    return render(request, "echeances/utilisateurs.html", {"utilisateurs": users, "form": form})


@login_required
@permission_required("auth.add_user", raise_exception=True)
def utilisateur_creer(request):
    form = UtilisateurForm(request.POST or None, request.FILES or None, editeur=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(request, f"Utilisateur « {user.username} » créé.")
        return redirect("utilisateurs")
    return render(request, "echeances/utilisateur_form.html", {"form": form})


# --- Tables de référence : banques et fournisseurs ---------------------------------------

class _ReferenceMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Création et modification d'une table de référence (réglée par les sous-classes)."""
    raise_exception = True
    template_name = "echeances/reference_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(titre_table=self.titre, url_liste=reverse(self.url_liste))
        return ctx

    def get_success_url(self):
        messages.success(self.request, f"« {self.object} » enregistré.")
        return reverse(self.url_liste)


class BanqueCreate(_ReferenceMixin, CreateView):
    model, form_class = Banque, BanqueForm
    permission_required = "echeances.add_banque"
    titre, url_liste = "Nouvelle banque", "banques"


class BanqueUpdate(_ReferenceMixin, UpdateView):
    model, form_class = Banque, BanqueForm
    permission_required = "echeances.change_banque"
    titre, url_liste = "Modifier la banque", "banques"


class FournisseurCreate(_ReferenceMixin, CreateView):
    model, form_class = Fournisseur, FournisseurForm
    permission_required = "echeances.add_fournisseur"
    titre, url_liste = "Nouveau fournisseur", "fournisseurs"


class FournisseurUpdate(_ReferenceMixin, UpdateView):
    model, form_class = Fournisseur, FournisseurForm
    permission_required = "echeances.change_fournisseur"
    titre, url_liste = "Modifier le fournisseur", "fournisseurs"


@login_required
@permission_required("echeances.view_banque", raise_exception=True)
def banques(request):
    q = request.GET.get("q", "").strip()
    qs = Banque.objects.all()
    if q:
        qs = qs.filter(Q(nom__icontains=q) | Q(code__icontains=q) | Q(numero_compte__icontains=q))
    return render(request, "echeances/banques.html", {"banques": qs, "q": q})


@login_required
@permission_required("echeances.view_fournisseur", raise_exception=True)
def fournisseurs(request):
    q = request.GET.get("q", "").strip()
    qs = Fournisseur.objects.all()
    if q:
        qs = qs.filter(Q(nom__icontains=q) | Q(telephone__icontains=q) | Q(email__icontains=q))
    return render(request, "echeances/fournisseurs.html", {"fournisseurs": qs, "q": q})


# --- Profil de l'utilisateur connecté ----------------------------------------------------

@login_required
def profil(request):
    form = ProfilForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Votre profil a été mis à jour.")
        return redirect("profil")
    return render(request, "echeances/profil.html", {"form": form})


# --- Détails, modification des utilisateurs et suppressions -----------------------------------

class _Suppression(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    """Page de confirmation puis suppression. Une suppression refusée (données liées) est expliquée."""
    raise_exception = True
    template_name = "echeances/confirmer_suppression.html"
    url_liste = None
    detail_protege = "Des données y sont rattachées."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(url_retour=reverse(self.url_liste), objet_libelle=str(self.object))
        return ctx

    def get_success_url(self):
        return reverse(self.url_liste)

    def form_valid(self, form):
        libelle = str(self.object)
        try:
            reponse = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, f"« {libelle} » ne peut pas être supprimé. {self.detail_protege}")
            return redirect(self.url_liste)
        messages.success(self.request, f"« {libelle} » a été supprimé.")
        return reponse


class EcheanceDelete(_Suppression):
    model = Echeance
    permission_required = "echeances.delete_echeance"
    url_liste = "liste"


class BanqueDetail(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Banque
    permission_required = "echeances.view_banque"
    raise_exception = True
    template_name = "echeances/reference_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        o = self.object
        ctx.update(
            titre_table=o.nom, url_liste=reverse("banques"), url_modifier="banque_modifier",
            champs=[("Nom", o.nom), ("Numéro de compte", o.numero_compte or "—"), ("Code court", o.code or "—"),
                    ("Statut", "Active" if o.actif else "Inactive")],
            echeances=o.echeances.select_related("fournisseur").order_by("-date_echeance")[:15],
            peut_modifier=self.request.user.has_perm("echeances.change_banque"),
        )
        return ctx


class FournisseurDetail(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Fournisseur
    permission_required = "echeances.view_fournisseur"
    raise_exception = True
    template_name = "echeances/reference_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        o = self.object
        ctx.update(
            titre_table=o.nom, url_liste=reverse("fournisseurs"), url_modifier="fournisseur_modifier",
            champs=[("Nom", o.nom), ("Téléphone", o.telephone or "—"), ("E-mail", o.email or "—"),
                    ("Statut", "Actif" if o.actif else "Inactif")],
            echeances=o.echeances.select_related("banque").order_by("-date_echeance")[:15],
            peut_modifier=self.request.user.has_perm("echeances.change_fournisseur"),
        )
        return ctx


class BanqueDelete(_Suppression):
    model = Banque
    permission_required = "echeances.delete_banque"
    url_liste = "banques"
    detail_protege = "Elle est utilisée par des échéances ; désactivez-la plutôt."


class FournisseurDelete(_Suppression):
    model = Fournisseur
    permission_required = "echeances.delete_fournisseur"
    url_liste = "fournisseurs"
    detail_protege = "Il est utilisé par des échéances ; désactivez-le plutôt."


class UtilisateurDetail(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = get_user_model()
    permission_required = "auth.view_user"
    raise_exception = True
    template_name = "echeances/utilisateur_detail.html"
    context_object_name = "utilisateur"


class UtilisateurUpdate(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = get_user_model()
    form_class = UtilisateurModifierForm
    permission_required = "auth.change_user"
    raise_exception = True
    template_name = "echeances/utilisateur_form.html"
    context_object_name = "utilisateur"

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["files"] = self.request.FILES or None
        kw["editeur"] = self.request.user
        return kw

    def get_success_url(self):
        messages.success(self.request, f"Utilisateur « {self.object.username} » modifié.")
        return reverse("utilisateurs")


class UtilisateurDelete(_Suppression):
    model = get_user_model()
    permission_required = "auth.delete_user"
    url_liste = "utilisateurs"
    context_object_name = "utilisateur"

    def get(self, request, *args, **kwargs):
        if self.get_object() == request.user:
            messages.error(request, "Vous ne pouvez pas supprimer votre propre compte.")
            return redirect("utilisateurs")
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        if self.object == self.request.user:
            messages.error(self.request, "Vous ne pouvez pas supprimer votre propre compte.")
            return redirect("utilisateurs")
        return super().form_valid(form)


# --- Périodes (filtre des échéances et tableau de bord) ----------------------------------------

@login_required
@permission_required("echeances.view_periode", raise_exception=True)
def periodes(request):
    return render(request, "echeances/periodes.html", {"periodes": Periode.objects.all()})


class PeriodeCreate(_ReferenceMixin, CreateView):
    model, form_class = Periode, PeriodeForm
    permission_required = "echeances.add_periode"
    titre, url_liste = "Nouvelle période", "periodes"


class PeriodeUpdate(_ReferenceMixin, UpdateView):
    model, form_class = Periode, PeriodeForm
    permission_required = "echeances.change_periode"
    titre, url_liste = "Modifier la période", "periodes"


class PeriodeDelete(_Suppression):
    model = Periode
    permission_required = "echeances.delete_periode"
    url_liste = "periodes"


# --- Journal d'audit -----------------------------------------------------------------------

AUDIT_OBJETS = {
    "echeance": ("Échéance", Echeance, "echeance_detail"),
    "banque": ("Banque", Banque, "banque_detail"),
    "fournisseur": ("Fournisseur", Fournisseur, "fournisseur_detail"),
    "periode": ("Période", Periode, None),
    "parametres": ("Alertes e-mail", ParametresAlertes, None),
    "entreprise": ("Entreprise", Entreprise, None),
}
AUDIT_ACTIONS = {"+": ("Création", "statut--PAYEE"), "~": ("Modification", "statut--A_VENIR"), "-": ("Suppression", "statut--IMPAYEE")}
AUDIT_IGNORES = ["modifie_le", "cree_le"]


def _audit_libelle(cle, h):
    if cle == "parametres":
        return "Serveur e-mail et paliers d'alerte"
    if cle == "entreprise":
        return "Informations de l'entreprise"
    if cle == "echeance":
        return f"{h.get_type_display()} du {h.date_echeance:%d/%m/%Y} — {int(h.montant):,} F CFA".replace(",", "\u202f")
    return getattr(h, "libelle", None) or h.nom


def _audit_valeur(champ, v):
    """Valeur lisible d'un champ pour le journal : libellé d'un choix, date en jj/mm/aaaa, oui/non, montant espacé."""
    if v in ("", None):
        return "(vide)"
    if champ.choices:
        return str(dict(champ.flatchoices).get(v, v))
    if isinstance(v, bool):
        return "oui" if v else "non"
    if hasattr(v, "strftime"):
        return v.strftime("%d/%m/%Y")
    if champ.get_internal_type() == "DecimalField":
        return f"{int(v):,}".replace(",", " ")
    return str(v)


def _audit_changements(h):
    """Liste « champ : ancien → nouveau » pour une modification (les clés étrangères : juste le nom du champ)."""
    prev = h.prev_record
    if h.history_type != "~" or prev is None:
        return []
    out = []
    for c in h.diff_against(prev, excluded_fields=AUDIT_IGNORES).changes:
        champ = h.instance_type._meta.get_field(c.field)
        nom = str(champ.verbose_name)
        nom = nom[:1].upper() + nom[1:]
        if champ.is_relation or c.field in ("piece_jointe", "logo"):
            out.append(f"{nom} modifié(e)")
        else:
            out.append(f"{nom} : {_audit_valeur(champ, c.old)} → {_audit_valeur(champ, c.new)}")
    return out


@login_required
@permission_required("echeances.view_historicalecheance", raise_exception=True)
def journal_audit(request):
    form = FiltreAuditForm(request.GET or None)
    d = form.cleaned_data if form.is_valid() else {}

    def filtrer(qs, champ_date, champ_user, champ_action):
        if d.get("action"):
            qs = qs.filter(**{champ_action: d["action"]})
        if d.get("utilisateur"):
            qs = qs.filter(**{champ_user: d["utilisateur"]})
        if d.get("du"):
            qs = qs.filter(**{champ_date + "__date__gte": d["du"]})
        if d.get("au"):
            qs = qs.filter(**{champ_date + "__date__lte": d["au"]})
        return qs

    evenements = []  # (date, cle, enregistrement)
    for cle, (_, modele, _) in AUDIT_OBJETS.items():
        if d.get("objet") and d["objet"] != cle:
            continue
        qs = filtrer(modele.history.select_related("history_user"), "history_date", "history_user", "history_type")
        evenements += [(h.history_date, cle, h) for h in qs.order_by("-history_date")[:1000]]
    if d.get("objet") in (None, "", "role"):
        qs = filtrer(EvenementRole.objects.select_related("utilisateur"), "date", "utilisateur", "action")
        evenements += [(e.date, "role", e) for e in qs[:1000]]
    evenements.sort(key=lambda e: e[0], reverse=True)

    page = Paginator(evenements, 50).get_page(request.GET.get("page"))
    lignes = []
    for date, cle, h in page:
        if cle == "role":
            lignes.append({
                "date": date, "utilisateur": h.utilisateur, "action": AUDIT_ACTIONS[h.action], "type": "Rôle",
                "libelle": h.nom, "url": None, "changements": [l for l in h.detail.split("\n") if l],
            })
            continue
        type_objet, modele, url = AUDIT_OBJETS[cle]
        existe = h.history_type != "-" and modele.objects.filter(pk=h.id).exists()
        lignes.append({
            "date": date, "utilisateur": h.history_user,
            "action": AUDIT_ACTIONS[h.history_type], "type": type_objet,
            "libelle": _audit_libelle(cle, h),
            "url": reverse(url, args=[h.id]) if url and existe else None,
            "changements": _audit_changements(h),
        })
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "echeances/journal_audit.html", {
        "form": form, "page": page, "lignes": lignes, "querystring": params.urlencode(),
    })


# --- Rôles (groupes de permissions) --------------------------------------------------------

@login_required
@permission_required("auth.view_group", raise_exception=True)
def roles(request):
    qs = Group.objects.annotate(
        nb_droits=Count("permissions", distinct=True), nb_utilisateurs=Count("user", distinct=True),
    ).order_by("name")
    return render(request, "echeances/roles.html", {"roles": qs})


class _RoleMixin(LoginRequiredMixin, PermissionRequiredMixin):
    raise_exception = True
    model = Group
    form_class = RoleForm
    template_name = "echeances/role_form.html"

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["editeur"] = self.request.user
        return kw

    def get_success_url(self):
        messages.success(self.request, f"Rôle « {self.object.name} » enregistré.")
        return reverse("roles")


class RoleCreate(_RoleMixin, CreateView):
    permission_required = "auth.add_group"


class RoleUpdate(_RoleMixin, UpdateView):
    permission_required = "auth.change_group"


class RoleDelete(_Suppression):
    model = Group
    permission_required = "auth.delete_group"
    url_liste = "roles"

    def form_valid(self, form):
        if self.object.user_set.exists():
            messages.error(self.request, f"Le rôle « {self.object.name} » est attribué à des utilisateurs : retirez-le d'abord.")
            return redirect("roles")
        nom = self.object.name
        reponse = super().form_valid(form)
        EvenementRole.objects.create(utilisateur=self.request.user, action="-", nom=nom)
        return reponse


# --- Fichiers téléversés (photos, pièces jointes) : accessibles aux seuls utilisateurs connectés ------

@login_required
def fichier_media(request, chemin):
    from django.conf import settings
    from django.http import FileResponse, Http404
    from django.utils._os import safe_join

    if chemin.startswith("pieces/") and not request.user.has_perm("echeances.view_echeance"):
        raise Http404
    try:
        complet = safe_join(settings.MEDIA_ROOT, chemin)
    except Exception:
        raise Http404
    import os
    if not os.path.isfile(complet):
        raise Http404
    if settings.DEBUG:
        return FileResponse(open(complet, "rb"))
    # En production, Nginx envoie le fichier lui-même (emplacement interne /protected-media/).
    reponse = HttpResponse()
    reponse["X-Accel-Redirect"] = "/protected-media/" + chemin
    reponse["Content-Type"] = ""  # laisse Nginx déterminer le type
    return reponse


# --- Alertes e-mail : serveur d'envoi et paliers ---------------------------------------------

@login_required
@permission_required("echeances.gerer_parametres_alertes", raise_exception=True)
def parametres_alertes(request):
    from . import mail

    p = ParametresAlertes.charger()
    form = ParametresAlertesForm(request.POST or None, instance=p)
    if request.method == "POST" and form.is_valid():
        if request.POST.get("action") == "tester":
            d = form.cleaned_data
            if not request.user.email:
                messages.error(request, "Renseignez d'abord votre adresse e-mail dans votre profil : le test y est envoyé.")
            else:
                ok, detail = mail.envoyer_test(
                    request.user.email, d["hote"], d["port"], d["securite"], d["utilisateur"],
                    d["mot_de_passe"] or p.mot_de_passe(), d["expediteur_nom"], d["expediteur_adresse"],
                )
                (messages.success if ok else messages.error)(request, detail)
        else:
            form.save()
            messages.success(request, "Paramètres enregistrés.")
            return redirect("parametres_alertes")
    return render(request, "echeances/parametres_alertes.html", {"form": form, "parametres": p})


# --- Entreprise : nom, logo et coordonnées des documents imprimés ----------------------------

@login_required
@permission_required("echeances.change_entreprise", raise_exception=True)
def entreprise(request):
    e = Entreprise.charger()
    form = EntrepriseForm(request.POST or None, request.FILES or None, instance=e)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Informations de l'entreprise enregistrées.")
        return redirect("entreprise")
    return render(request, "echeances/entreprise.html", {"form": form, "entreprise": e})
