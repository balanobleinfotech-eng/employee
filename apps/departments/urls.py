from django.urls import path
from . import views

app_name = 'departments'

urlpatterns = [
    path('', views.department_list, name='list'),
    path('<int:pk>/edit/', views.department_update, name='edit'),
    path('<int:pk>/delete/', views.department_delete, name='delete'),
    path('designation/<int:pk>/delete/', views.designation_delete, name='designation_delete'),
    path('branches/', views.branch_list, name='branches'),
    path('branches/<int:pk>/edit/', views.branch_update, name='branch_edit'),
    path('branches/<int:pk>/delete/', views.branch_delete, name='branch_delete'),
]
