import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.exceptions import PermissionDenied

class AttendanceConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        session_id = self.scope['url_route']['kwargs']['session_id']
        self.group_name = f"attendance_{session_id}"
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close(code=4401)
            return
        # Authorization: only teacher of session or enrolled student may join
        is_allowed = await self._is_allowed(user, session_id)
        if not is_allowed:
            await self.close(code=4403)
            return
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    @database_sync_to_async
    def _is_allowed(self, user, session_id):
        try:
            from .models import AttendanceSession
            from classroom.models import Enrollment
            session = AttendanceSession.objects.select_related('classroom').get(id=session_id)
            if user == session.teacher or user.is_superuser:
                return True
            return Enrollment.objects.filter(student=user, classroom=session.classroom).exists()
        except Exception:
            return False

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            try:
                await self.channel_layer.group_discard(self.group_name, self.channel_name)
            except: pass

    async def receive(self, text_data):
        # Server push only; ignore client messages but validate JSON
        try:
            data = json.loads(text_data) if text_data else {}
            # Optionally handle ping
            if data.get('type') == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))
        except: pass

    async def attendance_update(self, event):
        # Only send data, no sensitive fields
        try:
            await self.send(text_data=json.dumps(event["data"]))
        except: pass
