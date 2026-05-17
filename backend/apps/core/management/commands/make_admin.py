"""
Usage:
    docker compose exec api python manage.py make_admin <username>

Promotes any existing user to admin role and makes them a superuser.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = "Promote a user to admin role"

    def add_arguments(self, parser):
        parser.add_argument("username", type=str, help="Username to promote to admin")

    def handle(self, *args, **options):
        username = options["username"]
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"User '{username}' not found."))
            self.stderr.write("Existing users:")
            for u in User.objects.all():
                self.stderr.write(f"  - {u.username} (role={u.role})")
            return

        user.role         = "admin"
        user.is_superuser = True
        user.is_staff     = True
        user.save()
        self.stdout.write(self.style.SUCCESS(
            f"Done! '{username}' is now an admin.\n"
            f"Log in at http://localhost:3000 with username: {username}"
        ))
