from django.http import JsonResponse
from django.db import connection
from django.utils import timezone

def health_check(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return JsonResponse({"status": "ok", "time": timezone.now().isoformat(), "db": "ok"})
    except Exception as e:
        return JsonResponse({"status": "error", "error": str(e)}, status=500)
