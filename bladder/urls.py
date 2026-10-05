from django.urls import path
from . import views

app_name = "bladder"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("operador/", views.operador_turno, name="operador"),
    path("operador/fechar-turno/", views.fechamento_turno, name="fechamento_turno"),
    path("operador/iniciar/<int:pk>/", views.operador_iniciar, name="operador_iniciar"),
    path("operador/apontar/<int:pk>/", views.operador_apontar, name="operador_apontar"),
    path("operador/corrigir/<int:pk>/", views.corrigir_apontamento, name="corrigir_apontamento"),
    path("cronograma/", views.cronograma_calendario, name="cronograma"),
    path("ordens/", views.ordens_lista, name="ordens_lista"),
    path("ordens/nova/", views.ordem_nova, name="ordem_nova"),
    path("ordens/<int:pk>/", views.ordem_detalhe, name="ordem_detalhe"),
    path("ordens/<int:pk>/reprogramar/", views.ordem_reprogramar, name="ordem_reprogramar"),
    path("ordens/<int:pk>/cancelar/", views.ordem_cancelar, name="ordem_cancelar"),
    path("ordens/<int:pk>/encerrar-parcial/", views.encerrar_parcial_view, name="encerrar_parcial"),
    path("api/saldo-produto/<int:produto_id>/", views.api_saldo_produto, name="api_saldo_produto"),
    path("api/escala-dia/", views.api_escala_dia, name="api_escala_dia"),
    path("relatorios/", views.relatorios, name="relatorios"),
    path("relatorios/exportar-excel/", views.relatorios_exportar_excel, name="relatorios_exportar_excel"),
]
