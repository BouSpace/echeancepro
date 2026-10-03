from django.utils import timezone

from .models import Echeance


def compteurs(request):
    """Nombre d'échéances en retard, affiché dans la barre de navigation."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    return {"nb_en_retard": Echeance.objects.en_retard(timezone.localdate()).count()}
