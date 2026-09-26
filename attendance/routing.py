from django.urls import re_path
from .consumers import AttendanceConsumer

websocket_urlpatterns = [
    re_path(r'ws/attendance/(?P<session_id>[^/]+)/$', AttendanceConsumer.as_asgi()),
]
