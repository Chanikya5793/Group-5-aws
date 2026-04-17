from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile


@receiver(post_save, sender=get_user_model())
def ensure_user_profile(sender, instance, created, **kwargs):
    """Ensure every auth user always has a profile with a role."""
    defaults = {
        "role": "admin" if (instance.is_superuser or instance.is_staff) else "patient",
    }

    profile, _ = UserProfile.objects.get_or_create(user=instance, defaults=defaults)

    # Keep superusers aligned with admin role even if profile existed earlier.
    if (instance.is_superuser or instance.is_staff) and profile.role != "admin":
        profile.role = "admin"
        profile.save(update_fields=["role"])
