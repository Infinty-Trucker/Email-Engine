"""HTTP views for mail-rule management.

Tenant-aware: results are filtered to the caller's tenant (mc_number),
which Email-Engine resolves via the user's CompanyUser links. Falls back
to staff-only for global rules.
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.automations.models import MailRule, MailRuleExecution
from apps.automations.serializers import (
    MailRuleExecutionSerializer,
    MailRuleSerializer,
)


def _user_mc_numbers(user) -> list[str]:
    """Resolve the tenants the user can act on.

    Email-Engine links users to tenants via ``User.assigned_companies``
    (see apps/users/models.py).
    """
    if not user.is_authenticated:
        return []
    return list(user.assigned_companies.values_list("mc_number", flat=True))


class MailRuleListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        mcs = _user_mc_numbers(request.user)
        qs = MailRule.objects.select_related("company").all()
        if not (request.user.is_staff or request.user.is_superuser):
            qs = qs.filter(company__mc_number__in=mcs)
        data = MailRuleSerializer(qs, many=True).data
        return Response(data)

    def post(self, request):
        serializer = MailRuleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Ensure non-staff callers can only create rules for their tenants.
        if not (request.user.is_staff or request.user.is_superuser):
            company = serializer.validated_data.get("company")
            mcs = _user_mc_numbers(request.user)
            if company is None or company.mc_number not in mcs:
                return Response(
                    {"detail": "Not allowed to create rule for that tenant."},
                    status=status.HTTP_403_FORBIDDEN,
                )
        rule = serializer.save()
        return Response(MailRuleSerializer(rule).data, status=status.HTTP_201_CREATED)


class MailRuleDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, rule_id):
        try:
            rule = MailRule.objects.select_related("company").get(id=rule_id)
        except MailRule.DoesNotExist:
            return None
        if not (request.user.is_staff or request.user.is_superuser):
            mcs = _user_mc_numbers(request.user)
            if rule.company_id is None or rule.company.mc_number not in mcs:
                return None
        return rule

    def get(self, request, rule_id):
        rule = self._get(request, rule_id)
        if rule is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(MailRuleSerializer(rule).data)

    def patch(self, request, rule_id):
        rule = self._get(request, rule_id)
        if rule is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = MailRuleSerializer(rule, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        rule = serializer.save()
        return Response(MailRuleSerializer(rule).data)

    def delete(self, request, rule_id):
        rule = self._get(request, rule_id)
        if rule is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        rule.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MailRuleExecutionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        mcs = _user_mc_numbers(request.user)
        qs = (
            MailRuleExecution.objects.select_related("rule", "rule__company", "message")
            .order_by("-attempted_at")[:200]
        )
        if not (request.user.is_staff or request.user.is_superuser):
            qs = qs.filter(rule__company__mc_number__in=mcs)
        data = MailRuleExecutionSerializer(qs, many=True).data
        return Response(data)
