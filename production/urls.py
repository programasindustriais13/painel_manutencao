from django.urls import path
from . import views

app_name = "production"

urlpatterns = [
    path("", views.production_dashboard, name="dashboard"),
    path("maquinas/<int:pk>/", views.machine_detail, name="machine_detail"),
    path("maquinas/<int:machine_id>/cavidades/<int:cavity_id>/", views.cavity_detail, name="cavity_detail"),
    path("plano-turno/", views.pcp_plan_list, name="shift_plan"),
    path("metas/", views.pcp_plan_list, name="target_list"),
    path("metas/criar/", views.pcp_plan_create, name="target_create"),
    path("metas/<int:pk>/editar/", views.target_edit, name="target_edit"),
    path("metas/<int:pk>/cancelar/", views.target_cancel, name="target_cancel"),
    path("catalogos/matrizes/", views.catalog_list, name="catalog_list"),
    path("bladders/", views.bladder_list, name="bladder_list"),
    path("bladders/historico/", views.bladder_history, name="bladder_history"),
    path("bladders/detalhe/", views.bladder_detail, name="bladder_detail_query"),
    path("bladders/<int:pk>/", views.bladder_detail, name="bladder_detail"),
    path("pcp/", views.pcp_plan_list, name="pcp_plan_list"),
    path("pcp/nova/", views.pcp_plan_create, name="pcp_plan_create"),
    path("pcp/<int:pk>/", views.pcp_plan_detail, name="pcp_plan_detail"),
    path("pcp/<int:pk>/editar/", views.pcp_plan_edit, name="pcp_plan_edit"),
    path("pcp/<int:pk>/cancelar/", views.pcp_plan_cancel, name="pcp_plan_cancel"),
    path("pcp/<int:pk>/excluir/", views.pcp_plan_delete, name="pcp_plan_delete"),
    path("pcp/api/calcular/", views.pcp_api_calculate, name="pcp_api_calculate"),
    # Central de Configuração SCADA e Cadastro Organizado de XIDs
    path("configuracao-scada/", views.xid_config_dashboard, name="xid_config_dashboard"),
    path("configuracao-scada/maquinas/<int:pk>/", views.xid_machine_config, name="xid_machine_config"),
    path("configuracao-scada/globais/", views.xid_global_config, name="xid_global_config"),
    path("configuracao-scada/api/testar-xid/", views.xid_test_api, name="xid_test_api"),
]


