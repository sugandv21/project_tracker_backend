from django.urls import path, include
from rest_framework import routers
from .views import MiniProjectViewSet, MeView, UserListView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

router = routers.DefaultRouter()
router.register(r"mini-projects", MiniProjectViewSet, basename="mini-projects")

urlpatterns = [
    path("", include(router.urls)),      # e.g. /api/mini-projects/
    path("me/", MeView.as_view(), name="me"),
    path("users/", UserListView.as_view(), name="users-list"),
    path("token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
]
