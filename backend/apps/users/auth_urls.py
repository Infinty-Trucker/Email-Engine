from django.urls import path
from .views import csrf_view, login_view, logout_view, me_view

urlpatterns = [
    path("csrf/",   csrf_view),
    path("login/",  login_view),
    path("logout/", logout_view),
    path("me/",     me_view),
]
