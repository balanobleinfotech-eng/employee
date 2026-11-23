from django.contrib import admin
from .models import Department, Designation, Branch

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'employee_count', 'created_at')
    search_fields = ('name', 'code')

@admin.register(Designation)
class DesignationAdmin(admin.ModelAdmin):
    list_display = ('title', 'department')
    search_fields = ('title', 'department__name')
    list_filter = ('department',)

@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'latitude', 'longitude', 'radius_meters', 'is_active', 'employee_count', 'created_at')
    search_fields = ('name', 'code', 'address')
    list_filter = ('is_active',)
