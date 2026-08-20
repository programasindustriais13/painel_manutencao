from django.urls import path
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from . import views

urlpatterns = [
    # PWA: Service Worker servido da raiz para escopo global
    path('service-worker.js', views.service_worker_view, name='service_worker'),
    
    # Home redirect based on role
    path('', views.home_redirect, name='home_redirect'),
    path('portal/', views.portal_select, name='portal_select'),
    
    # Authentication views
    path('login/', auth_views.LoginView.as_view(template_name='maintenance/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    
    # Core Dashboards
    path('tv/', views.tv_dashboard, name='tv_dashboard'),
    path('management/', views.technician_management, name='technician_management'),
    path('dashboard/', views.dashboard, name='dashboard'),
    
    # Real-time state transitions (por technician_id)
    path('technicians/<int:technician_id>/start/', views.start_service, name='start_service'),
    path('technicians/<int:technician_id>/pause/', views.pause_service, name='pause_service'),
    path('technicians/<int:technician_id>/resume/', views.resume_service, name='resume_service'),
    path('technicians/<int:technician_id>/finish/', views.finish_service, name='finish_service'),
    path('technicians/<int:technician_id>/availability/', views.set_availability, name='set_availability'),
    
    # Ações sobre alocações específicas (por allocation_id — suporte a múltiplas alocações)
    path('allocations/<int:allocation_id>/resume/', views.resume_paused_allocation, name='resume_paused_allocation'),
    path('allocations/<int:allocation_id>/finish/', views.finish_allocation, name='finish_allocation'),
    path('allocations/<int:allocation_id>/update-progress/', views.add_allocation_progress_update, name='add_allocation_progress_update'),
    path('anexos/alocacoes/<int:allocation_id>/', views.serve_allocation_attachment, name='serve_allocation_attachment'),
    
    # CRUD central page
    path('cruds/', views.crud_list, name='crud_list'),

    # Relatório de Passagem de Turno
    path('relatorio-turno/', views.relatorio_turno, name='relatorio_turno'),

    # Exportação de relatório Excel
    path('dashboard/exportar-excel/', views.exportar_relatorio_excel, name='exportar_relatorio_excel'),

    # Sector CRUD
    path('sectors/create/', views.sector_create, name='sector_create'),
    path('sectors/<int:pk>/edit/', views.sector_edit, name='sector_edit'),
    path('sectors/<int:pk>/delete/', views.sector_delete, name='sector_delete'),
    
    # Machine CRUD
    path('machines/create/', views.machine_create, name='machine_create'),
    path('machines/<int:pk>/edit/', views.machine_edit, name='machine_edit'),
    path('machines/<int:pk>/delete/', views.machine_delete, name='machine_delete'),
    
    # Technician CRUD
    path('technicians/create/', views.technician_create, name='technician_create'),
    path('technicians/<int:pk>/edit/', views.technician_edit, name='technician_edit'),
    path('technicians/<int:pk>/delete/', views.technician_delete, name='technician_delete'),

    # AI / Vision OCR API
    path('api/os/extrair-foto/', views.extrair_dados_os_foto_api, name='api_extrair_dados_os_foto'),
    path('api/os/verificar-numero/', views.api_verificar_numero_os, name='api_verificar_numero_os'),

    # Ordem de Serviço (Quadro, Criação por Foto & Ações de Atendimento)
    path('ordens-servico/', views.os_board, name='os_board'),
    path('ordens-servico/<int:pk>/', views.os_detail, name='os_detail'),
    path('ordens-servico/nova/', views.os_create, name='os_create'),
    path('ordens-servico/<int:os_id>/atribuir/', views.os_assign_technician, name='os_assign_technician'),
    path('ordens-servico/<int:os_id>/iniciar/', views.os_start_service, name='os_start_service'),
    path('ordens-servico/<int:os_id>/entrar-equipe/', views.os_join_team, name='os_join_team'),
    path('ordens-servico/<int:os_id>/cancelar/', views.os_cancel, name='os_cancel'),
    path('allocations/<int:allocation_id>/vincular-os/', views.link_allocation_os, name='link_allocation_os'),
]





