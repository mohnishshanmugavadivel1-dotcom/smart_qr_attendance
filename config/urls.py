from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from attendance.views import dashboard_router
from config.health import health_check

urlpatterns = [
    path('admin/', admin.site.urls),
    path('health/', health_check, name='health'),
    path('', RedirectView.as_view(url='/dashboard/', permanent=False)),
    path('dashboard/', dashboard_router, name='dashboard'),
    path('accounts/', include('accounts.urls')),
    path('classroom/', include('classroom.urls')),
    path('attendance/', include('attendance.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
