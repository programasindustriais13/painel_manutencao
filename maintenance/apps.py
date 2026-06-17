from django.apps import AppConfig


class MaintenanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "maintenance"

    def ready(self):
        # Garante a criação dos grupos nativos no startup
        try:
            from django.contrib.auth.models import Group
            Group.objects.get_or_create(name='Tecnicos')
            Group.objects.get_or_create(name='Tecnicos_Lideres')
            Group.objects.get_or_create(name='Operadores')
        except Exception:
            pass
