from django.urls import path

from apps.automations.views import (
    MailRuleListCreateView,
    MailRuleDetailView,
    MailRuleExecutionListView,
)

urlpatterns = [
    path("rules/", MailRuleListCreateView.as_view(), name="mail-rules-list"),
    path("rules/<uuid:rule_id>/", MailRuleDetailView.as_view(), name="mail-rule-detail"),
    path(
        "executions/",
        MailRuleExecutionListView.as_view(),
        name="mail-rule-executions",
    ),
]
