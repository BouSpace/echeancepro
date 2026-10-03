from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse_lazy

from echeances import views

admin.site.site_header = "ÉchéancePro — administration"
admin.site.site_title = "ÉchéancePro"
admin.site.index_title = "Paramètres et référentiels"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("connexion/", auth_views.LoginView.as_view(), name="login"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
    path("profil/mot-de-passe/", auth_views.PasswordChangeView.as_view(
        template_name="registration/mot_de_passe.html", success_url=reverse_lazy("profil")), name="mot_de_passe"),
    path("media/<path:chemin>", views.fichier_media, name="media"),
    path("", include("echeances.urls")),
]
