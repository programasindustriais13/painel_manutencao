from django.urls import path
from . import views

app_name = "matrizaria"

urlpatterns = [
    # Kanban Principal
    path("", views.kanban_view, name="kanban"),

    # Fluxo de Atendimento
    path("solicitar/", views.solicitar_servico_view, name="solicitar_servico"),
    path("servicos/<int:pk>/", views.detalhe_servico_view, name="detalhe_servico"),
    path("servicos/<int:pk>/editar/", views.editar_solicitacao_view, name="editar_solicitacao"),
    path("servicos/<int:pk>/iniciar/", views.iniciar_atendimento_view, name="iniciar_atendimento"),
    path("servicos/<int:pk>/transferir/", views.transferir_responsabilidade_view, name="transferir_responsabilidade"),
    path("servicos/<int:pk>/finalizar/", views.finalizar_execucao_view, name="finalizar_execucao"),
    path("servicos/<int:pk>/conferir/", views.conferir_servico_view, name="conferir_servico"),
    path("servicos/<int:pk>/cancelar/", views.cancelar_servico_view, name="cancelar_servico"),

    # Relatórios e Exportação
    path("relatorios/", views.relatorios_view, name="relatorios"),
    path("relatorios/exportar-excel/", views.exportar_excel_view, name="exportar_excel"),

    # Painel de TV
    path("tv/", views.tv_view, name="tv"),
    path("api/tv-data/", views.api_tv_data_view, name="api_tv_data"),
]
