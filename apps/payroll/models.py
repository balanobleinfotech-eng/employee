from django.db import models
from apps.employees.models import Employee

class SalaryStructure(models.Model):
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name='salary_structure')
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    hra = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    allowances = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    pf_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    tax_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total_earnings(self):
        return self.basic_salary + self.hra + self.allowances

    @property
    def total_deductions(self):
        return self.pf_deduction + self.tax_deduction

    @property
    def net_salary(self):
        return max(0, self.total_earnings - self.total_deductions)

    def __str__(self):
        return f"{self.employee.employee_code} - Net: ₹{self.net_salary:.2f}"


class PayrollRecord(models.Model):
    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Unpaid', 'Unpaid'),
        ('Partially Paid', 'Partially Paid'),
        ('Paid', 'Paid'),
    )
    PAYMENT_MODES = (
        ('Bank Transfer', 'Bank Transfer (NEFT/RTGS/IMPS)'),
        ('UPI', 'UPI Payment'),
        ('Cash', 'Cash'),
        ('Cheque', 'Company Cheque'),
    )

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='payroll_records')
    year = models.IntegerField()
    month = models.IntegerField()
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2)
    allowances = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    advance_salary_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Advance Salary Deducted")
    overtime_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)
    overtime_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    present_days = models.DecimalField(max_digits=5, decimal_places=1, default=0.0)
    absent_days = models.DecimalField(max_digits=5, decimal_places=1, default=0.0)
    paid_leaves = models.DecimalField(max_digits=5, decimal_places=1, default=0.0)
    unpaid_leaves = models.DecimalField(max_digits=5, decimal_places=1, default=0.0)
    permission_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    net_salary = models.DecimalField(max_digits=12, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    payment_date = models.DateField(null=True, blank=True)
    payment_mode = models.CharField(max_length=50, choices=PAYMENT_MODES, default='Bank Transfer')
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('employee', 'year', 'month')
        ordering = ['-year', '-month', 'employee__employee_code']
        verbose_name = 'Payroll Record'
        verbose_name_plural = 'Payroll Records'

    def __str__(self):
        return f"{self.employee.employee_code} - {self.month}/{self.year} (₹{self.net_salary:.2f})"

    @property
    def pending_amount(self):
        if self.status == 'Paid':
            return 0.00
        return max(0.00, float(self.net_salary) - float(self.paid_amount))


class AdvanceSalary(models.Model):
    STATUS_CHOICES = (
        ('Pending', 'Pending HR Approval'),
        ('Approved', 'Approved for Disbursement'),
        ('Deducted', 'Deducted from Monthly Payroll'),
        ('Rejected', 'Rejected'),
    )

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='advance_salaries')
    request_date = models.DateField(auto_now_add=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Advance Amount Requested")
    reason = models.TextField(blank=True, verbose_name="Reason for Advance")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    deduct_in_month = models.IntegerField(null=True, blank=True, verbose_name="Deduction Target Month (1-12)")
    deduct_in_year = models.IntegerField(null=True, blank=True, verbose_name="Deduction Target Year")
    approved_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Advance Salary Request'
        verbose_name_plural = 'Advance Salary Requests'

    def __str__(self):
        return f"{self.employee.employee_code} - Advance ₹{self.amount} ({self.status})"
