from rest_framework import serializers
from .models import User


class UserSerializer(serializers.ModelSerializer):
    assigned_companies = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    assigned_company_ids = serializers.PrimaryKeyRelatedField(
        many=True, write_only=True,
        queryset=__import__('apps.companies.models', fromlist=['Company']).Company.objects.all(),
        source='assigned_companies', required=False
    )

    class Meta:
        model = User
        fields = ["id","username","email","first_name","last_name","role",
                  "assigned_companies","assigned_company_ids","is_active","is_superuser"]
        read_only_fields = ["id","is_superuser"]
        extra_kwargs = {"password": {"write_only": True, "required": False}}
