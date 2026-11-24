import os
import mimetypes
from django.shortcuts import render, redirect, get_object_or_404
from django.http import FileResponse, Http404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from apps.users.decorators import hr_or_admin_required, admin_required
from .models import Employee
from .forms import EmployeeCreateForm, EmployeeUpdateForm

from datetime import timedelta, datetime
from django.utils import timezone
from apps.attendance.models import DailyWorkPlan

@login_required
@hr_or_admin_required
def employee_list(request):
    today = timezone.localdate()
    next_day_date = today + timedelta(days=1)

    # Handle Work Plan assignment from Employee Page
    if request.method == 'POST' and request.POST.get('action') == 'create_work_plan':
        emp_id = request.POST.get('employee_id')
        target_emp = get_object_or_404(Employee, id=emp_id)
        work_date_str = request.POST.get('work_date')
        tasks = request.POST.get('tasks', '').strip()
        plan_title = request.POST.get('title', '').strip() or 'Daily Work Plan & Responsibilities'
        status_val = request.POST.get('status', 'Assigned')
        try:
            work_date = datetime.strptime(work_date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            work_date = next_day_date

        if not tasks:
            messages.error(request, "Please enter specific tasks or deliverables for the work plan.")
        else:
            DailyWorkPlan.objects.create(
                employee=target_emp,
                work_date=work_date,
                title=plan_title,
                tasks=tasks,
                status=status_val,
                assigned_by=request.user
            )
            messages.success(request, f"Daily work plan assigned successfully to {target_emp.display_name()} for {work_date.strftime('%B %d, %Y')}!")
        return redirect('employees:list')

    # Handle Work Plan deletion
    if request.method == 'POST' and request.POST.get('action') == 'delete_work_plan':
        plan_id = request.POST.get('plan_id')
        plan = get_object_or_404(DailyWorkPlan, id=plan_id)
        emp_name = plan.employee.display_name()
        plan.delete()
        messages.success(request, f"Work plan for {emp_name} deleted successfully.")
        return redirect('employees:list')

    query = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', '')
    dept_filter = request.GET.get('department', '')
    work_location_filter = request.GET.get('work_location', '')

    employees = Employee.objects.select_related('user', 'department', 'designation', 'branch').all()

    if query:
        employees = employees.filter(
            Q(employee_code__icontains=query) |
            Q(user__username__icontains=query) |
            Q(user__first_name__icontains=query) |
            Q(user__last_name__icontains=query) |
            Q(phone__icontains=query) |
            Q(department__name__icontains=query)
        )

    if role_filter:
        employees = employees.filter(role=role_filter)
    if dept_filter:
        employees = employees.filter(department_id=dept_filter)
    if work_location_filter == 'ONSITE':
        employees = employees.filter(is_offsite_employee=False)
    elif work_location_filter == 'OFFSITE':
        employees = employees.filter(is_offsite_employee=True)

    daily_work_plans = DailyWorkPlan.objects.select_related('employee__user', 'assigned_by').order_by('-work_date', '-created_at')[:40]
    all_active_employees = Employee.objects.filter(is_active_employee=True).select_related('user', 'department').order_by('employee_code')

    from apps.departments.models import Department
    context = {
        'employees': employees,
        'departments': Department.objects.all(),
        'query': query,
        'role_filter': role_filter,
        'dept_filter': dept_filter,
        'work_location_filter': work_location_filter,
        'onsite_count': Employee.objects.filter(is_offsite_employee=False).count(),
        'offsite_count': Employee.objects.filter(is_offsite_employee=True).count(),
        'total_count': employees.count(),
        'daily_work_plans': daily_work_plans,
        'all_active_employees': all_active_employees,
        'next_day_date': next_day_date,
    }
    return render(request, 'employees/employee_list.html', context)

@login_required
def employee_detail(request, pk):
    employee = get_object_or_404(
        Employee.objects.select_related('user', 'department', 'designation'), pk=pk
    )
    # Check access permission: user can view own profile or HR/Admin can view any
    current_profile = getattr(request.user, 'employee', None)
    if current_profile != employee and (not current_profile or current_profile.role not in ('ADMIN', 'HR')):
        messages.error(request, "Permission denied to view another employee's file.")
        return redirect('dashboard:index')

    attendances = employee.attendances.all()[:15]
    leaves = employee.leave_requests.all()[:10]
    daily_works = employee.daily_works.all()[:10]
    payroll_records = employee.payroll_records.all()[:12]

    context = {
        'employee': employee,
        'attendances': attendances,
        'leaves': leaves,
        'daily_works': daily_works,
        'payroll_records': payroll_records,
    }
    return render(request, 'employees/employee_detail.html', context)

@login_required
@hr_or_admin_required
def employee_create(request):
    if request.method == 'POST':
        form = EmployeeCreateForm(request.POST, request.FILES)
        if form.is_valid():
            employee = form.save()
            messages.success(request, f"Employee '{employee.display_name()}' ({employee.employee_code}) created successfully!")
            return redirect('employees:detail', pk=employee.pk)
        else:
            for err_list in form.errors.values():
                for err in err_list:
                    messages.error(request, err)
    else:
        form = EmployeeCreateForm()

    return render(request, 'employees/employee_form.html', {'form': form, 'title': 'Register New Employee'})

@login_required
@hr_or_admin_required
def employee_update(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == 'POST':
        form = EmployeeUpdateForm(request.POST, request.FILES, instance=employee)
        if form.is_valid():
            form.save()
            messages.success(request, f"Employee '{employee.display_name()}' updated successfully!")
            return redirect('employees:detail', pk=employee.pk)
        else:
            for err_list in form.errors.values():
                for err in err_list:
                    messages.error(request, err)
    else:
        form = EmployeeUpdateForm(instance=employee)

    return render(request, 'employees/employee_form.html', {
        'form': form,
        'title': f'Edit Employee - {employee.employee_code}',
        'employee': employee
    })

@login_required
@hr_or_admin_required
def employee_delete(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    current_profile = getattr(request.user, 'employee', None)
    is_admin = request.user.is_superuser or (current_profile and current_profile.role == 'ADMIN')

    # Main admin (NETCOM or superuser) can NEVER be deleted
    if employee.user.username.upper() == 'NETCOM' or employee.user.is_superuser:
        messages.error(request, "The main system administrator (NETCOM) cannot be deleted under any circumstances.")
        return redirect(request.META.get('HTTP_REFERER') or 'dashboard:index')

    if employee.user == request.user:
        messages.error(request, "You cannot delete your own active account.")
        return redirect(request.META.get('HTTP_REFERER') or 'dashboard:index')

    # HR cannot delete an administrator
    if not is_admin and employee.role == 'ADMIN':
        messages.error(request, "HR Managers cannot delete Administrator accounts.")
        return redirect(request.META.get('HTTP_REFERER') or 'dashboard:index')

    name = employee.display_name()
    user = employee.user
    user.delete()  # Cascades to employee
    messages.success(request, f"Account and records for '{name}' deleted permanently.")
    return redirect(request.META.get('HTTP_REFERER') or 'dashboard:index')


@login_required
def download_employee_file(request, pk, file_type):
    """
    Secure file download view for HR and Admin:
    - file_type: 'photo' (profile picture) or 'document' (submitted doc)
    - Sets Content-Disposition: attachment; filename="..." with proper MIME type
    """
    employee = get_object_or_404(Employee, pk=pk)
    current_profile = getattr(request.user, 'employee', None)
    is_authorized = (
        request.user.is_superuser
        or request.user.is_staff
        or (current_profile and current_profile.role in ('ADMIN', 'HR'))
        or employee.user == request.user
    )
    if not is_authorized:
        messages.error(request, "Permission denied to download employee files.")
        return redirect('dashboard:index')

    if file_type == 'photo':
        field = employee.profile_picture
        default_name = f"{employee.employee_code}_Profile_Picture"
    elif file_type == 'document':
        field = employee.document
        default_name = f"{employee.employee_code}_Document"
    else:
        raise Http404("Invalid file type requested.")

    if not field:
        messages.error(request, f"No {file_type} uploaded for employee {employee.display_name()}.")
        return redirect(request.META.get('HTTP_REFERER') or 'dashboard:index')

    try:
        file_path = field.path
        if not os.path.exists(file_path):
            messages.error(request, f"File not found on server for employee {employee.display_name()}.")
            return redirect(request.META.get('HTTP_REFERER') or 'dashboard:index')

        content_type, _ = mimetypes.guess_type(file_path)
        content_type = content_type or 'application/octet-stream'

        ext = os.path.splitext(field.name)[1]
        filename = f"{default_name}{ext}"

        return FileResponse(open(file_path, 'rb'), content_type=content_type, as_attachment=True, filename=filename)
    except Exception as e:
        messages.error(request, f"Error downloading file: {e}")
        return redirect(request.META.get('HTTP_REFERER') or 'dashboard:index')
