from django.urls import path
from . import views

app_name = 'classroom'
urlpatterns = [
    path('', views.classroom_list, name='list'),
    path('create/', views.create_classroom, name='create_class'),
    path('subject/create/', views.create_subject, name='create_subject'),
    path('<int:class_id>/manage/', views.manage_enrollment, name='manage'),
    path('<int:class_id>/enroll/', views.enroll_self, name='enroll_self'),
]
