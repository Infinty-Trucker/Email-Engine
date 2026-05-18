from django.urls import path, include

urlpatterns = [
    path("auth/",          include("apps.users.auth_urls")),
    path("companies/",     include("apps.companies.urls")),
    path("mailboxes/",     include("apps.mailboxes.urls")),
    path("conversations/", include("apps.conversations.urls")),
    path("approvals/",     include("apps.approvals.urls")),
    path("compliance/",    include("apps.classifier.urls")),
    path("users/",         include("apps.users.urls")),
    path("slack/",         include("apps.notifications.urls")),
    path("system/",        include("apps.core.urls")),
    path("automations/",   include("apps.automations.urls")),
]
