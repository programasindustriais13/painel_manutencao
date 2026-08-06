from django.urls import path
from . import views

app_name = "production"

urlpatterns = [
    path("", views.production_dashboard, name="dashboard"),
    path("maquinas/<int:pk>/", views.machine_detail, name="machine_detail"),
    path("maquinas/<int:machine_id>/cavidades/<int:cavity_id>/", views.cavity_detail, name="cavity_detail"),
    path("plano-turno/", views.target_list, name="shift_plan"),
    path("metas/", views.target_list, name="target_list"),
    path("metas/criar/", views.target_create, name="target_create"),
    path("metas/<int:pk>/editar/", views.target_edit, name="target_edit"),
    path("metas/<int:pk>/cancelar/", views.target_cancel, name="target_cancel"),
    path("catalogos/matrizes/", views.catalog_list, name="catalog_list"),
]

