from django.urls import path
from . import views

urlpatterns = [
    # Slack
    path("slack/",                      views.slack_get),
    path("slack/token/",                views.slack_save_token),
    path("slack/channels/",             views.slack_save_channels),
    path("slack/channels/list/",        views.slack_list_channels),
    path("slack/channels/registry/",    views.slack_channels_registry),
    path("slack/channels/registry/<uuid:channel_id>/", views.slack_channel_registry_delete),
    path("slack/channels/registry/<uuid:channel_id>/test/", views.slack_channel_registry_test),
    path("slack/test/connection/",      views.slack_test_connection),
    path("slack/test/channel/",         views.slack_test_channel),

    # Google Service Accounts (Workspace)
    path("google/accounts/",            views.sa_list),
    path("google/accounts/create/",     views.sa_create),
    path("google/accounts/<uuid:sa_id>/",          views.sa_detail),
    path("google/accounts/<uuid:sa_id>/upload/",   views.sa_upload_json),
    path("google/accounts/<uuid:sa_id>/test/",     views.sa_test),

    # OAuth App config
    path("oauth/app/",                  views.oauth_app_list),
    path("oauth/app/save/",             views.oauth_app_save),
    path("oauth/app/<uuid:app_id>/delete/", views.oauth_app_delete),

    # OAuth flow
    path("oauth/begin/",               views.oauth_begin),
    path("oauth/callback/",            views.oauth_callback),
    path("oauth/credentials/",         views.oauth_credentials_list),
    path("oauth/credentials/<uuid:cred_id>/", views.oauth_credential_delete),

    # Mailboxes
    path("mailboxes/",                  views.mailbox_list),
    path("mailboxes/create/",           views.mailbox_create),
    path("mailboxes/<uuid:mb_id>/",     views.mailbox_detail),
    path("mailboxes/<uuid:mb_id>/watch/register/", views.mailbox_register_watch),
    path("mailboxes/<uuid:mb_id>/watch/stop/",     views.mailbox_stop_watch),
    path("mailboxes/<uuid:mb_id>/test/",             views.mailbox_test_connection),
    path("mailboxes/<uuid:mb_id>/sync/",             views.mailbox_sync),

    # Health
    path("health/",                     views.system_health),

    # Diagnostics
    path("diagnostics/",                views.full_diagnostics),
    path("slack/test/all/",             views.slack_send_test),
]
