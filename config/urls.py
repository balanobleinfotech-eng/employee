from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.views.generic.base import RedirectView
from django.views.static import serve
from django.http import HttpResponse
from apps.users import views as user_views

import os
from django.shortcuts import render

def robots_txt_view(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        "Allow: /login/",
        "Allow: /static/",
        "Disallow: /dashboard/",
        "Disallow: /django-admin/",
        "Disallow: /attendance/",
        "Disallow: /leave/",
        "Disallow: /payroll/",
        "Disallow: /employees/",
        "Disallow: /departments/",
        "Disallow: /reports/",
        "Disallow: /users/verify-admin-access/",
        "",
        f"Sitemap: {request.scheme}://{request.get_host()}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain; charset=utf-8")

def sitemap_xml_view(request):
    base_url = f"{request.scheme}://{request.get_host()}"
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{base_url}/login/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>{base_url}/</loc>
    <changefreq>daily</changefreq>
    <priority>0.9</priority>
  </url>
</urlset>"""
    return HttpResponse(content.strip(), content_type="application/xml; charset=utf-8")

def safe_serve_media(request, path, document_root=None, show_indexes=False):
    root = document_root or settings.MEDIA_ROOT
    full_path = os.path.join(str(root), path)
    if not os.path.exists(full_path):
        return render(request, 'errors/media_not_found.html', {
            'path': path,
            'filename': os.path.basename(path)
        }, status=404)
    return serve(request, path, document_root=root, show_indexes=show_indexes)

urlpatterns = [
    # Search Engine Optimization & Crawling (SEO)
    path('robots.txt', robots_txt_view, name='robots_txt'),
    path('sitemap.xml', sitemap_xml_view, name='sitemap_xml'),

    # Favicon support
    path('favicon.ico', RedirectView.as_view(url='/static/images/netcom_logo.png', permanent=True)),

    # Django Administration Backend
    path('django-admin/', admin.site.urls),
    path('admin/', RedirectView.as_view(url='/django-admin/', permanent=False)),

    # Authentication Routes (Exact preservation of /login/ and /logout/ URLs)
    path('', user_views.root_redirect_view, name='home'),
    path('login/', user_views.custom_login_view, name='login'),
    path('logout/', user_views.custom_logout_view, name='logout'),

    # Modular App Endpoints
    path('dashboard/', include('apps.dashboard.urls', namespace='dashboard')),
    path('employees/', include('apps.employees.urls', namespace='employees')),
    path('departments/', include('apps.departments.urls', namespace='departments')),
    path('attendance/', include('apps.attendance.urls', namespace='attendance')),
    path('leave/', include('apps.leave_management.urls', namespace='leave_management')),
    path('payroll/', include('apps.payroll.urls', namespace='payroll')),
    path('reports/', include('apps.reports.urls', namespace='reports')),
    path('users/', include('apps.users.urls', namespace='users')),

    # Safe Media files serving in all environments
    re_path(r'^media/(?P<path>.*)$', safe_serve_media, {'document_root': settings.MEDIA_ROOT}),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
