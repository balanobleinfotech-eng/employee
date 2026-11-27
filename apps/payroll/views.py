import io
import calendar
from decimal import Decimal
from datetime import date, timedelta, datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from apps.users.decorators import hr_or_admin_required
from apps.employees.models import Employee
from apps.attendance.models import Attendance
from apps.leave_management.models import LeaveRequest
from .models import SalaryStructure, PayrollRecord, AdvanceSalary
from .forms import SalaryStructureForm, GeneratePayrollForm

def calculate_payroll_for_employee(emp, year, month):
    """
    Implements mandatory attendance-based salary calculations:
    1. 9 working hours (>= 540m) count as a full working day -> Full-day salary (no deduction).
    2. 4 hours and 30 minutes (>= 270m and < 540m) count as a half working day -> Half-day salary (0.5 day deducted).
    3. Up to 2 hours of approved permission -> Must not affect salary (no deduction).
    4. Approved leave days -> Must not result in salary deductions (no deduction).
    5. Unexcused absence -> 1.0 day deducted.
    6. Overtime beyond 9 hours -> Credited at hourly rate.
    7. Advance salary -> Deducted if scheduled for this billing period.
    """
    days_in_month = calendar.monthrange(year, month)[1]
    structure = getattr(emp, 'salary_structure', None)

    if structure:
        basic = structure.basic_salary
        hra = structure.hra
        allowances = structure.allowances
        gross_salary = structure.total_earnings
        statutory_deductions = structure.total_deductions
    else:
        basic = emp.basic_salary
        hra = Decimal('0.00')
        allowances = Decimal('0.00')
        gross_salary = basic
        statutory_deductions = Decimal('0.00')

    daily_rate = (gross_salary / Decimal(str(days_in_month))).quantize(Decimal('0.01'))
    hourly_rate = (daily_rate / Decimal('9.0')).quantize(Decimal('0.01'))

    month_start = date(year, month, 1)
    month_end = date(year, month, days_in_month)

    # 1. Collect approved leave days in this month
    approved_leaves = LeaveRequest.objects.filter(
        employee=emp, status='Approved',
        from_date__lte=month_end, to_date__gte=month_start
    )
    paid_leave_days = set()
    unpaid_leave_days = set()

    for l in approved_leaves:
        if l.leave_type in ('Permission', 'Permission (Up to 2 Hours)') or 'Permission' in l.approval_type:
            continue
        curr = max(l.from_date, month_start)
        end = min(l.to_date, month_end)
        while curr <= end:
            if not l.is_paid or l.approval_type == 'Unpaid Leave' or l.leave_type == 'Unpaid Leave':
                unpaid_leave_days.add(curr.day)
            else:
                paid_leave_days.add(curr.day)
            curr += timedelta(days=1)

    # Include Office-wide Paid Leaves (Full Pay, zero deduction)
    from apps.leave_management.models import OfficePaidLeave
    for opl in OfficePaidLeave.objects.filter(date__year=year, date__month=month):
        paid_leave_days.add(opl.date.day)

    # Exclude attendances and absence evaluations prior to employee joining date
    joining_date = getattr(emp, 'joining_date', None)
    if joining_date:
        earliest_att = Attendance.objects.filter(employee=emp).order_by('date').values_list('date', flat=True).first()
        if earliest_att and earliest_att < joining_date:
            joining_date = earliest_att

    # 2. Inspect attendances in this month (strictly starting from joining date)
    attendances_qs = Attendance.objects.filter(
        employee=emp, date__year=year, date__month=month
    )

    if joining_date and joining_date > month_end and not attendances_qs.exists():
        return {
            'basic_salary': Decimal('0.00'),
            'allowances': Decimal('0.00'),
            'deductions': Decimal('0.00'),
            'net_salary': Decimal('0.00'),
            'remarks': f"Employee official joining date ({joining_date.strftime('%b %d, %Y')}) is after this billing period.",
            'full_days': 0,
            'half_days': 0,
            'permission_days': 0,
            'approved_leaves': 0,
            'present_days': Decimal('0.0'),
            'absent_days': Decimal('0.0'),
            'paid_leaves': Decimal('0.0'),
            'unpaid_leaves': Decimal('0.0'),
            'permission_hours': Decimal('0.00'),
            'overtime_hours': Decimal('0.00'),
            'overtime_amount': Decimal('0.00'),
            'advance_salary_deduction': Decimal('0.00'),
            'advance_ids': [],
            'incomplete_punch_days': [],
        }

    pre_joining_days = 0
    if joining_date and joining_date > month_start:
        pre_joining_days = (joining_date - month_start).days

    if joining_date:
        attendances_qs = attendances_qs.filter(date__gte=joining_date)

    full_days = 0
    half_days = 0
    permission_days = 0
    total_permission_minutes = 0
    overtime_minutes = 0
    absent_days = 0
    paid_leave_count = 0
    unpaid_leave_count = 0
    seen_attendance_days = set()

    recorded_absent_days = set()
    incomplete_punch_days = []
    for a in attendances_qs:
        d = a.date.day
        seen_attendance_days.add(d)

        # Track approved permission duration in minutes
        perm_mins = a.approved_permission_minutes
        if perm_mins > 0:
            total_permission_minutes += perm_mins

        # Official duty counts as full day Present with full pay
        if getattr(a, 'is_official_duty', False) or a.update_source == 'Official Office Duty' or a.leave_type == 'Official Duty':
            full_days += 1
            continue

        # Incomplete attendance: punch-in is recorded but punch-out is missing
        if getattr(a, 'is_missing_punch_out', False) or (a.in_time and not a.out_time):
            incomplete_punch_days.append(d)
            recorded_absent_days.add(d)
            continue

        # If day is in leave and employee did not perform actual work
        if d in paid_leave_days and (not a.in_time and a.total_work_minutes < 270):
            paid_leave_count += 1
            continue
        elif d in unpaid_leave_days and (not a.in_time and a.total_work_minutes < 270):
            unpaid_leave_count += 1
            recorded_absent_days.add(d)
            continue

        calc_mins = a.total_calculated_minutes
        if calc_mins > 540 and a.out_time:
            # Overtime hours beyond standard 9 hours
            overtime_minutes += (calc_mins - 540)

        if a.status == 'Permission - 2 Hours' or a.is_permission:
            # Approved permission -> zero deduction
            permission_days += 1
        elif a.status in ('On Leave', 'Office Holiday') or a.leave_type == 'Paid Leave for the Office':
            if a.leave_type == 'Unpaid Leave' or a.status == 'Leave Without Pay (LWP)':
                unpaid_leave_count += 1
                recorded_absent_days.add(d)
            else:
                paid_leave_count += 1
        elif a.status == 'Present' or calc_mins >= 540:
            # 9 working hours -> full working day, full-day salary (only if punch-out is present)
            if a.out_time:
                full_days += 1
            else:
                incomplete_punch_days.append(d)
                recorded_absent_days.add(d)
        elif a.status == 'Half Day' or (270 <= calc_mins < 540):
            # 4h 30m -> half working day, half-day salary (only if punch-out is present)
            if a.out_time:
                half_days += 1
            else:
                incomplete_punch_days.append(d)
                recorded_absent_days.add(d)
        elif a.status in ('Absent', 'Missed Punch-In', 'Leave Without Pay (LWP)'):
            absent_days += 1
            recorded_absent_days.add(d)

    # Check Sunday sandwich continuous absence rule (up to 5 days continuous absence encompassing Sunday)
    sandwich_sunday_count = 0
    for day_num in range(1, days_in_month + 1):
        cur_d = date(year, month, day_num)
        if joining_date and cur_d < joining_date:
            continue
        if cur_d.weekday() == 6:  # Sunday
            sat_absent = (day_num - 1) in recorded_absent_days
            mon_absent = (day_num + 1) in recorded_absent_days
            if sat_absent and mon_absent:
                sandwich_sunday_count += 1

    # Add any approved leaves that didn't have an Attendance record row yet (strictly after joining)
    filtered_paid_leave_days = {d for d in paid_leave_days if not (joining_date and date(year, month, d) < joining_date)}
    filtered_unpaid_leave_days = {d for d in unpaid_leave_days if not (joining_date and date(year, month, d) < joining_date)}
    unlinked_paid = len(filtered_paid_leave_days - seen_attendance_days)
    unlinked_unpaid = len(filtered_unpaid_leave_days - seen_attendance_days)
    total_paid_leaves = paid_leave_count + unlinked_paid
    total_unpaid_leaves = unpaid_leave_count + unlinked_unpaid + sandwich_sunday_count

    # Uncorrected missing punch-outs default to Leave Without Pay (LWP) per policy
    unique_incomplete_days = sorted(list(set(incomplete_punch_days)))
    total_unpaid_leaves += len(unique_incomplete_days)

    half_day_deduction = (Decimal(str(half_days)) * Decimal('0.5') * daily_rate).quantize(Decimal('0.01'))
    absent_deduction = (Decimal(str(absent_days)) * daily_rate).quantize(Decimal('0.01'))
    unpaid_leave_deduction = (Decimal(str(total_unpaid_leaves)) * daily_rate).quantize(Decimal('0.01'))

    # Overtime calculation
    overtime_hours = (Decimal(str(overtime_minutes)) / Decimal('60.0')).quantize(Decimal('0.01'))
    overtime_amount = (overtime_hours * hourly_rate).quantize(Decimal('0.01'))

    # Advance salary deduction check
    pending_advances = AdvanceSalary.objects.filter(
        employee=emp,
        status__in=['Approved', 'Pending']
    ).filter(
        deduct_in_year=year,
        deduct_in_month=month
    )
    advance_deduction = Decimal('0.00')
    advance_ids = []
    for adv in pending_advances:
        advance_deduction += adv.amount
        advance_ids.append(adv.id)

    attendance_deductions = half_day_deduction + absent_deduction + unpaid_leave_deduction
    total_deductions = statutory_deductions + attendance_deductions + advance_deduction
    net_salary = max(Decimal('0.00'), gross_salary + overtime_amount - total_deductions)

    total_perm_hrs = (Decimal(str(total_permission_minutes)) / Decimal('60.0')).quantize(Decimal('0.01'))
    present_days_count = Decimal(str(round(full_days + (half_days * 0.5), 1)))

    remarks = (
        f"Attended: Full Days: {full_days}, Half Days: {half_days} (-₹{half_day_deduction:.2f}), "
        f"Approved Permission: {total_perm_hrs}h ({permission_days} days, Full Pay), "
        f"Paid Leaves/Holidays: {total_paid_leaves} (Full Pay), "
        f"Unpaid Leaves: {total_unpaid_leaves} (-₹{unpaid_leave_deduction:.2f}), "
        f"Absents: {absent_days} (-₹{absent_deduction:.2f}). "
    )
    if overtime_amount > 0:
        remarks += f"[Overtime: {overtime_hours}h (+₹{overtime_amount:.2f})]. "
    if advance_deduction > 0:
        remarks += f"[Advance Salary Deducted: -₹{advance_deduction:.2f}]. "
    if pre_joining_days > 0:
        remarks += f"[Pre-Joining: {pre_joining_days} days excluded]. "
    if sandwich_sunday_count > 0:
        remarks += f"[Sandwich Sundays: {sandwich_sunday_count} to LWP]. "
    if unique_incomplete_days:
        remarks += f"[Incomplete attendance (missing punch-out) on day(s) {unique_incomplete_days}]. "

    return {
        'basic_salary': basic,
        'allowances': hra + allowances,
        'deductions': total_deductions,
        'net_salary': net_salary,
        'remarks': remarks.strip(),
        'full_days': full_days,
        'half_days': half_days,
        'permission_days': permission_days,
        'approved_leaves': total_paid_leaves,
        'present_days': present_days_count,
        'absent_days': Decimal(str(absent_days)),
        'paid_leaves': Decimal(str(total_paid_leaves)),
        'unpaid_leaves': Decimal(str(total_unpaid_leaves)),
        'permission_hours': total_perm_hrs,
        'overtime_hours': overtime_hours,
        'overtime_amount': overtime_amount,
        'advance_salary_deduction': advance_deduction,
        'advance_ids': advance_ids,
        'incomplete_punch_days': unique_incomplete_days,
    }

@login_required
def payroll_list(request):
    profile = getattr(request.user, 'employee', None)
    is_management = profile and profile.role in ('ADMIN', 'HR')

    selected_year = int(request.GET.get('year', date.today().year))
    selected_month = int(request.GET.get('month', date.today().month))
    emp_filter = request.GET.get('employee_id', '').strip()
    status_filter = request.GET.get('status', '').strip()

    if is_management:
        records_qs = PayrollRecord.objects.select_related(
            'employee', 'employee__user', 'employee__department', 'employee__designation', 'employee__branch'
        ).filter(year=selected_year, month=selected_month)

        if emp_filter:
            records_qs = records_qs.filter(employee_id=emp_filter)
        if status_filter:
            records_qs = records_qs.filter(status=status_filter)

        records = list(records_qs)
        all_employees = Employee.objects.filter(is_active_employee=True).select_related('user', 'department').order_by('employee_code')
        advance_salaries = AdvanceSalary.objects.select_related('employee', 'employee__user').order_by('-created_at')[:20]
    else:
        records = list(PayrollRecord.objects.select_related('employee', 'employee__department').filter(employee=profile, year=selected_year, month=selected_month))
        all_employees = []
        advance_salaries = AdvanceSalary.objects.filter(employee=profile).order_by('-created_at')[:10]

    generate_form = GeneratePayrollForm(initial={'year': selected_year, 'month': selected_month})

    # Summary Metrics Calculation
    total_employees = len(records)
    total_payable = sum(r.net_salary for r in records)
    total_disbursed = sum(r.paid_amount if r.status in ('Paid', 'Partially Paid') and r.paid_amount > 0 else (r.net_salary if r.status == 'Paid' else Decimal('0.00')) for r in records)
    total_pending = max(Decimal('0.00'), total_payable - total_disbursed)

    context = {
        'records': records,
        'is_management': is_management,
        'generate_form': generate_form,
        'selected_year': selected_year,
        'selected_month': selected_month,
        'selected_emp_id': emp_filter,
        'selected_status': status_filter,
        'all_employees': all_employees,
        'advance_salaries': advance_salaries,
        'total_employees': total_employees,
        'total_payable': total_payable,
        'total_disbursed': total_disbursed,
        'total_pending': total_pending,
    }
    return render(request, 'payroll/payroll_list.html', context)

@login_required
@hr_or_admin_required
def generate_payroll(request):
    if request.method == 'POST':
        form = GeneratePayrollForm(request.POST)
        if form.is_valid():
            year = int(form.cleaned_data['year'])
            month = int(form.cleaned_data['month'])

            active_employees = Employee.objects.filter(is_active_employee=True)
            created_count = 0

            for emp in active_employees:
                calc = calculate_payroll_for_employee(emp, year, month)

                record, created = PayrollRecord.objects.update_or_create(
                    employee=emp,
                    year=year,
                    month=month,
                    defaults={
                        'basic_salary': calc['basic_salary'],
                        'allowances': calc['allowances'],
                        'deductions': calc['deductions'],
                        'net_salary': calc['net_salary'],
                        'present_days': calc['present_days'],
                        'absent_days': calc['absent_days'],
                        'paid_leaves': calc['paid_leaves'],
                        'unpaid_leaves': calc['unpaid_leaves'],
                        'permission_hours': calc['permission_hours'],
                        'overtime_hours': calc['overtime_hours'],
                        'overtime_amount': calc['overtime_amount'],
                        'advance_salary_deduction': calc['advance_salary_deduction'],
                        'remarks': calc['remarks'],
                    }
                )

                # Mark any deducted advance salary records
                if calc['advance_ids']:
                    AdvanceSalary.objects.filter(id__in=calc['advance_ids']).update(status='Deducted')

                if created:
                    created_count += 1

            messages.success(request, f"Payroll processed for {month}/{year}. Evaluated {active_employees.count()} employees with attendance, leave, permission, overtime & advance deductions.")
            return redirect(f"/payroll/?year={year}&month={month}")
    return redirect('payroll:list')

@login_required
def payslip_detail(request, pk):
    record = get_object_or_404(
        PayrollRecord.objects.select_related('employee', 'employee__user', 'employee__department', 'employee__designation', 'employee__branch'),
        pk=pk
    )
    profile = getattr(request.user, 'employee', None)
    if profile != record.employee and (not profile or profile.role not in ('ADMIN', 'HR')):
        messages.error(request, "Permission denied to view this payslip.")
        return redirect('payroll:list')

    month_name = date(2000, record.month, 1).strftime('%B')
    return render(request, 'payroll/payslip.html', {
        'record': record,
        'month_name': month_name,
    })

@login_required
@hr_or_admin_required
def mark_paid(request, pk):
    record = get_object_or_404(PayrollRecord, pk=pk)
    record.status = 'Paid'
    record.payment_date = date.today()
    record.paid_amount = record.net_salary
    record.save(update_fields=['status', 'payment_date', 'paid_amount'])
    messages.success(request, f"Payroll for {record.employee.display_name()} ({record.month}/{record.year}) marked as Paid.")
    return redirect(f"/payroll/?year={record.year}&month={record.month}")

@login_required
@hr_or_admin_required
def update_payment(request, pk):
    record = get_object_or_404(PayrollRecord, pk=pk)
    if request.method == 'POST':
        new_status = request.POST.get('status', record.status)
        payment_date_val = request.POST.get('payment_date', '').strip()
        payment_mode = request.POST.get('payment_mode', record.payment_mode)
        paid_amount_val = request.POST.get('paid_amount', '').strip()

        if new_status in ('Paid', 'Unpaid', 'Partially Paid', 'Pending'):
            record.status = new_status
        if payment_mode:
            record.payment_mode = payment_mode
        if payment_date_val:
            try:
                record.payment_date = datetime.strptime(payment_date_val, '%Y-%m-%d').date()
            except ValueError:
                pass
        elif new_status == 'Paid' and not record.payment_date:
            record.payment_date = date.today()

        if paid_amount_val:
            try:
                record.paid_amount = Decimal(paid_amount_val)
            except Exception:
                pass
        elif new_status == 'Paid':
            record.paid_amount = record.net_salary
        elif new_status == 'Unpaid':
            record.paid_amount = Decimal('0.00')

        record.save()
        messages.success(request, f"Payment details updated for {record.employee.display_name()} (Status: {record.status}, Mode: {record.payment_mode}).")
    return redirect(f"/payroll/?year={record.year}&month={record.month}")

@login_required
def advance_salary_manage(request):
    profile = getattr(request.user, 'employee', None)
    is_management = profile and profile.role in ('ADMIN', 'HR')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'request_advance':
            # Employee or HR requesting advance salary
            target_emp_id = request.POST.get('employee_id')
            if is_management and target_emp_id:
                target_emp = get_object_or_404(Employee, id=target_emp_id)
            else:
                target_emp = profile

            amount = Decimal(request.POST.get('amount', '0.00'))
            reason = request.POST.get('reason', '').strip()
            deduct_month = int(request.POST.get('deduct_month', date.today().month))
            deduct_year = int(request.POST.get('deduct_year', date.today().year))

            if amount <= 0:
                messages.error(request, "Please enter a valid positive advance amount.")
            else:
                AdvanceSalary.objects.create(
                    employee=target_emp,
                    amount=amount,
                    reason=reason,
                    status='Approved' if is_management else 'Pending',
                    deduct_in_month=deduct_month,
                    deduct_in_year=deduct_year,
                    approved_by=request.user if is_management else None
                )
                status_text = "Approved and scheduled" if is_management else "submitted for HR approval"
                messages.success(request, f"Advance salary request of ₹{amount:.2f} for {target_emp.display_name()} {status_text}.")

        elif action in ('approve_advance', 'reject_advance') and is_management:
            adv_id = request.POST.get('advance_id')
            adv = get_object_or_404(AdvanceSalary, id=adv_id)
            if action == 'approve_advance':
                adv.status = 'Approved'
                adv.approved_by = request.user
                messages.success(request, f"Advance salary of ₹{adv.amount:.2f} for {adv.employee.display_name()} Approved.")
            else:
                adv.status = 'Rejected'
                messages.warning(request, f"Advance salary request for {adv.employee.display_name()} Rejected.")
            adv.save()

    return redirect(request.META.get('HTTP_REFERER') or 'payroll:list')

@login_required
@hr_or_admin_required
def export_payroll(request, format_type):
    selected_year = int(request.GET.get('year', date.today().year))
    selected_month = int(request.GET.get('month', date.today().month))
    emp_filter = request.GET.get('employee_id', '').strip()
    status_filter = request.GET.get('status', '').strip()

    records = PayrollRecord.objects.select_related(
        'employee', 'employee__user', 'employee__department', 'employee__designation', 'employee__branch'
    ).filter(year=selected_year, month=selected_month)

    if emp_filter:
        records = records.filter(employee_id=emp_filter)
    if status_filter:
        records = records.filter(status=status_filter)

    month_name = date(selected_year, selected_month, 1).strftime('%B')

    if format_type.lower() == 'excel':
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = f"Payroll {month_name} {selected_year}"

        # Title block
        ws.merge_cells('A1:Q1')
        title_cell = ws['A1']
        title_cell.value = f"NETCOM COMPUTERS - MONTHLY PAYROLL LEDGER ({month_name.upper()} {selected_year})"
        title_cell.font = Font(size=14, bold=True, color="FFFFFF")
        title_cell.fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 36

        headers = [
            "Emp Code", "Staff Name", "Department", "Work Type", "Branch",
            "Present Days", "Absent Days", "Paid Leaves", "Unpaid Leaves", "Permission (Hrs)",
            "Basic Salary (₹)", "Allowances (₹)", "Overtime Pay (₹)", "Advance Deducted (₹)", "Total Deductions (₹)",
            "Net Payout (₹)", "Status"
        ]

        ws.append(headers)
        ws.row_dimensions[2].height = 24

        hdr_fill = PatternFill(start_color="0284C7", end_color="0284C7", fill_type="solid")
        hdr_font = Font(color="FFFFFF", bold=True, size=11)
        thin_border = Border(
            left=Side(style='thin', color='CBD5E1'),
            right=Side(style='thin', color='CBD5E1'),
            top=Side(style='thin', color='CBD5E1'),
            bottom=Side(style='thin', color='CBD5E1')
        )

        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=2, column=col_num)
            cell.fill = hdr_fill
            cell.font = hdr_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border

        for r in records:
            work_type = "Offsite" if r.employee.is_offsite_employee else "Onsite"
            branch_name = r.employee.branch.name if r.employee.branch else "Head Office"
            row_data = [
                r.employee.employee_code,
                r.employee.display_name(),
                r.employee.department.name if r.employee.department else "-",
                work_type,
                branch_name,
                float(r.present_days),
                float(r.absent_days),
                float(r.paid_leaves),
                float(r.unpaid_leaves),
                float(r.permission_hours),
                float(r.basic_salary),
                float(r.allowances),
                float(r.overtime_amount),
                float(r.advance_salary_deduction),
                float(r.deductions),
                float(r.net_salary),
                r.status,
            ]
            ws.append(row_data)
            current_row = ws.max_row
            ws.row_dimensions[current_row].height = 20
            for c_idx in range(1, len(headers) + 1):
                c = ws.cell(row=current_row, column=c_idx)
                c.border = thin_border
                c.alignment = Alignment(vertical="center", horizontal="right" if c_idx >= 6 and c_idx <= 16 else "left")

        # Auto-adjust column widths
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

        out = io.BytesIO()
        wb.save(out)
        out.seek(0)
        response = HttpResponse(
            out.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response['Content-Disposition'] = f'attachment; filename="Payroll_{month_name}_{selected_year}.xlsx"'
        return response

    elif format_type.lower() == 'pdf':
        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(letter),
            leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'TitleStyle',
            parent=styles['Heading1'],
            fontSize=15,
            textColor=colors.HexColor('#1e3a8a'),
            alignment=1,
            spaceAfter=6
        )
        meta_style = ParagraphStyle(
            'MetaStyle',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#475569'),
            alignment=1,
            spaceAfter=14
        )
        table_hdr_style = ParagraphStyle('TH', fontSize=8, fontName='Helvetica-Bold', textColor=colors.white, alignment=1)
        table_cell_style = ParagraphStyle('TC', fontSize=8, fontName='Helvetica', alignment=0)
        table_cell_num = ParagraphStyle('TCN', fontSize=8, fontName='Helvetica', alignment=2)

        elements = []
        elements.append(Paragraph(f"<b>NETCOM COMPUTERS — MONTHLY PAYROLL REPORT</b>", title_style))
        elements.append(Paragraph(f"Billing Period: <b>{month_name} {selected_year}</b> | Total Staff: <b>{len(records)}</b>", meta_style))

        table_data = [[
            Paragraph("<b>Emp Code</b>", table_hdr_style),
            Paragraph("<b>Staff Name</b>", table_hdr_style),
            Paragraph("<b>Dept</b>", table_hdr_style),
            Paragraph("<b>Type</b>", table_hdr_style),
            Paragraph("<b>Present</b>", table_hdr_style),
            Paragraph("<b>Absent</b>", table_hdr_style),
            Paragraph("<b>Paid L.</b>", table_hdr_style),
            Paragraph("<b>Perm.</b>", table_hdr_style),
            Paragraph("<b>Basic (₹)</b>", table_hdr_style),
            Paragraph("<b>Allow. (₹)</b>", table_hdr_style),
            Paragraph("<b>Deduct. (₹)</b>", table_hdr_style),
            Paragraph("<b>Net Pay (₹)</b>", table_hdr_style),
            Paragraph("<b>Status</b>", table_hdr_style),
        ]]

        for r in records:
            w_type = "Offsite" if r.employee.is_offsite_employee else "Onsite"
            table_data.append([
                Paragraph(r.employee.employee_code, table_cell_style),
                Paragraph(r.employee.display_name(), table_cell_style),
                Paragraph(r.employee.department.code if r.employee.department else "-", table_cell_style),
                Paragraph(w_type, table_cell_style),
                Paragraph(f"{r.present_days:.1f}", table_cell_num),
                Paragraph(f"{r.absent_days:.1f}", table_cell_num),
                Paragraph(f"{r.paid_leaves:.0f}", table_cell_num),
                Paragraph(f"{r.permission_hours:.1f}h", table_cell_num),
                Paragraph(f"₹{r.basic_salary:,.2f}", table_cell_num),
                Paragraph(f"₹{r.allowances:,.2f}", table_cell_num),
                Paragraph(f"₹{r.deductions:,.2f}", table_cell_num),
                Paragraph(f"<b>₹{r.net_salary:,.2f}</b>", table_cell_num),
                Paragraph(r.status, table_cell_style),
            ])

        pdf_table = Table(table_data, colWidths=[60, 110, 60, 50, 45, 45, 45, 45, 65, 65, 65, 75, 55])
        pdf_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0284c7')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))

        elements.append(pdf_table)
        doc.build(elements)
        buffer.seek(0)

        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="Payroll_{month_name}_{selected_year}.pdf"'
        return response

    return redirect('payroll:list')
