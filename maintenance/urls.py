from django.urls import path
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from . import views

urlpatterns = [
    # Home redirect based on role
    path('', views.home_redirect, name='home_redirect'),
    
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
    
    # CRUD central page
    path('cruds/', views.crud_list, name='crud_list'),

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
]

