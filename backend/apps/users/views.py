from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from .models import User
from .serializers import UserSerializer


@api_view(["GET"])
@permission_classes([AllowAny])
def csrf_view(request):
    # Sets the csrftoken cookie AND returns it in JSON
    token = get_token(request)
    response = Response({"csrfToken": token})
    response.set_cookie(
        "csrftoken", token,
        samesite="Lax",
        httponly=False,  # JS must be able to read it
    )
    return response


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    username = request.data.get("username") or request.data.get("email")
    password = request.data.get("password")
    if not username or not password:
        return Response({"error": "Username and password are required."}, status=400)
    user = authenticate(request, username=username, password=password)
    if not user:
        return Response({"error": "Invalid username or password. Check your credentials and try again."}, status=400)
    if not user.is_active:
        return Response({"error": "This account has been deactivated. Contact your admin."}, status=403)
    # Ensure superusers always have admin role
    if user.is_superuser and user.role != "admin":
        user.role = "admin"
        user.save(update_fields=["role"])
    login(request, user)
    return Response(UserSerializer(user).data)


@api_view(["POST"])
def logout_view(request):
    logout(request)
    return Response({"ok": True})


@api_view(["GET"])
def me_view(request):
    # Ensure CSRF cookie is set so the frontend can send it with POST requests
    get_token(request)
    return Response(UserSerializer(request.user).data)


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by("first_name", "username")
    serializer_class = UserSerializer

    def get_permissions(self):
        """Only admins can create/update/delete users."""
        from rest_framework.permissions import IsAuthenticated
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        """Handle password on create."""
        password = self.request.data.get("password", "")
        assigned = self.request.data.get("assigned_company_ids", [])
        user = serializer.save()
        if password:
            user.set_password(password)
            user.save(update_fields=["password"])
        if assigned:
            from apps.companies.models import Company
            user.assigned_companies.set(Company.objects.filter(id__in=assigned))

    def create(self, request, *args, **kwargs):
        """Override to return full user data after creation."""
        from rest_framework import status as drf_status
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": str(serializer.errors)}, status=400)
        self.perform_create(serializer)
        return Response(self.get_serializer(serializer.instance).data, status=drf_status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        """Handle password on update (only if provided)."""
        password = self.request.data.get("password")
        user = serializer.save()
        if password and len(password) >= 8:
            user.set_password(password)
            user.save(update_fields=["password"])

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        user = self.get_object()
        user.is_active = False
        user.save(update_fields=["is_active"])
        return Response({"ok": True})
