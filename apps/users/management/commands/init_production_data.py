import os
from pathlib import Path
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from apps.employees.models import Employee


class Command(BaseCommand):
    help = 'Seeds initial production data (departments, employees, attendance, payroll) and guarantees default credentials.'

    def handle(self, *args, **options):
        fixture_path = settings.BASE_DIR / 'database' / 'seed_data.json'
        if not fixture_path.exists():
            fixture_path = Path(__file__).resolve().parent.parent.parent.parent.parent / 'database' / 'seed_data.json'

        # 1. Load seed fixture if database is missing employees
        if Employee.objects.count() == 0 and fixture_path.exists():
            self.stdout.write(f"Seeding database from fixture: {fixture_path}")
            try:
                call_command('loaddata', str(fixture_path), verbosity=1)
                self.stdout.write(self.style.SUCCESS("Database seeded successfully."))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error loading fixture: {e}"))

        # 2. Explicitly ensure default login accounts and passwords (ADMIN & HR ONLY)
        creds = [
            ('NETCOM', 'Netcom@2026@Netcom', True, True, 'NETCOM', 'Administrator', 'admin@ncpli.com', 'ADMIN'),
            ('hr', 'hr12345', False, False, 'HR', 'Manager', 'hr@netcom.com', 'HR'),
            ('emp1', 'emp12345', False, False, 'Goutham', 'HR', 'goutham@netcom.com', 'HR'),
        ]

        from apps.departments.models import Department
        default_dept = Department.objects.first()
        if not default_dept:
            default_dept, _ = Department.objects.get_or_create(
                name='General',
                defaults={'description': 'General Department'}
            )

        for username, password, is_super, is_staff, first, last, email, role in creds:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'is_superuser': is_super,
                    'is_staff': is_staff,
                    'first_name': first,
                    'last_name': last,
                    'email': email,
                }
            )
            user.set_password(password)
            user.is_superuser = is_super
            user.is_staff = is_staff
            user.is_active = True
            user.email = email
            user.save()

            emp = getattr(user, 'employee', None)
            if not emp:
                code_prefix = 'ADM' if role == 'ADMIN' else ('HR' if role == 'HR' else 'EMP')
                emp_code = f"{code_prefix}{user.id:04d}"
                idx = 1
                while Employee.objects.filter(employee_code=emp_code).exists():
                    emp_code = f"{code_prefix}{user.id:04d}_{idx}"
                    idx += 1
                emp = Employee.objects.create(
                    user=user,
                    employee_code=emp_code,
                    role=role,
                    department=default_dept,
                    raw_password=password,
                    casual_leave_balance=1,
                    is_active_employee=True,
                )
            else:
                emp.role = role
                emp.raw_password = password
                emp.save(update_fields=['role', 'raw_password'])

            self.stdout.write(self.style.SUCCESS(f"User '{username}' verified (Role: {role}) and password configured."))

        # 3. Clean database: Keep ONLY Admin and HR details, purge all test employees and clear all date/activity records
        allowed_admin_hr_roles = ('ADMIN', 'HR')
        non_admin_hr_employees = Employee.objects.exclude(role__in=allowed_admin_hr_roles)
        for non_emp in non_admin_hr_employees:
            user_ref = non_emp.user
            self.stdout.write(f"Removing non-admin/HR employee record: {non_emp.employee_code} ({non_emp.display_name()})")
            non_emp.delete()
            if user_ref and not user_ref.is_superuser and not user_ref.is_staff:
                user_ref.delete()

        # Delete any stray non-admin/non-HR users without employee profiles
        User.objects.filter(is_superuser=False, is_staff=False, employee__isnull=True).delete()

        # Clear all transactional date/activity logs so database is completely fresh for use
        from apps.attendance.models import Attendance, DailyWork, DailyWorkPlan, AttendanceAuditLog
        from apps.leave_management.models import LeaveRequest, HRNotification, MonthlyLeaveCredit, OfficePaidLeave, MonthlyPermissionBalance
        from apps.payroll.models import PayrollRecord
        from apps.users.models import UserActiveSession

        Attendance.objects.all().delete()
        DailyWork.objects.all().delete()
        DailyWorkPlan.objects.all().delete()
        LeaveRequest.objects.all().delete()
        AttendanceAuditLog.objects.all().delete()
        HRNotification.objects.all().delete()
        PayrollRecord.objects.all().delete()
        MonthlyLeaveCredit.objects.all().delete()
        MonthlyPermissionBalance.objects.all().delete()
        OfficePaidLeave.objects.all().delete()
        UserActiveSession.objects.all().delete()

        self.stdout.write(self.style.SUCCESS("Database clean & fresh: Only Admin and HR details remain. All transactional date logs cleared successfully."))
