from django.db import transaction
from django.contrib.auth.models import User
from rest_framework import serializers

from .models import MiniProject, TraineeProgress


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "email")


class UserWithRoleSerializer(serializers.ModelSerializer):
    """
    Expose profile.role as `role` so frontend can consume `/me/` response easily.
    """
    role = serializers.CharField(source="profile.role", read_only=True)

    class Meta:
        model = User
        fields = ("id", "username", "email", "role")

class TraineeProgressSerializer(serializers.ModelSerializer):
    trainee_details = UserSerializer(source="trainee", read_only=True)
    report_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = TraineeProgress
        fields = (
            "id", "trainee", "trainee_details", "status",
            "report", "report_url", "deployment_link", "github_link",
            "trainer_comment", "updated_at", "completed_at",
        )
        read_only_fields = ("updated_at",)

    def get_report_url(self, obj):
        request = self.context.get("request")
        if not obj.report:
            return None
        try:
            url = obj.report.url  # FieldFile
        except Exception:
            url = str(obj.report)  # plain string fallback
        if url.startswith("http://") or url.startswith("https://"):
            return url
        if request:
            return request.build_absolute_uri(url)
        # fallback: prefix with MEDIA_URL if request not available
        from django.conf import settings
        if url.startswith(settings.MEDIA_URL):
            return request.build_absolute_uri(url) if request else (settings.MEDIA_URL + url[len(settings.MEDIA_URL):])
        return url


class MiniProjectSerializer(serializers.ModelSerializer):
    """
    Serializer for MiniProject.

    Important:
      - assigned_to is writable as a list of user PKs (many=True).
      - created_by is read-only and should be set by the view (perform_create).
      - serializer.create/update only handle M2M assignment and normal fields.
    """
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), many=True, required=False, allow_empty=True
    )
    assigned_to_details = UserSerializer(source="assigned_to", many=True, read_only=True)
    progress_entries = TraineeProgressSerializer(many=True, read_only=True)

    class Meta:
        model = MiniProject
        fields = (
            "id",
            "title",
            "description",
            "assigned_to",
            "assigned_to_details",
            "priority",
            "due_date",
            "created_at",
            "updated_at",
            "created_by",
            "progress_entries",
        )
        # created_by is set by the view (perform_create), not by client
        read_only_fields = ("created_at", "updated_at", "created_by")

    def validate_due_date(self, value):
        """
        Normalize empty string or None -> None so DateField validation works consistently.
        """
        if value in ("", None):
            return None
        return value

    @transaction.atomic
    def create(self, validated_data):
        """
        Create a MiniProject instance while safely handling M2M assigned_to.
        NOTE: Do NOT set created_by here — the view should call serializer.save(created_by=...)
        to set that field. This avoids duplication of responsibility.
        """
        assigned_users = validated_data.pop("assigned_to", [])
        # create the object without created_by (view will set it via serializer.save(created_by=...))
        obj = MiniProject.objects.create(**validated_data)

        # set M2M if provided
        if assigned_users:
            obj.assigned_to.set(assigned_users)

        return obj

    @transaction.atomic
    def update(self, instance, validated_data):
        """
        Update normal fields and optionally update assigned_to M2M if provided.
        If assigned_to is explicitly provided as an empty list, it will clear the M2M.
        If assigned_to is omitted, M2M will remain unchanged.
        """
        assigned_users = validated_data.pop("assigned_to", None)

        # update simple fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # update M2M only when provided in payload
        if assigned_users is not None:
            instance.assigned_to.set(assigned_users)

        return instance

    def to_representation(self, instance):
        """
        Limit progress_entries visible to trainees: trainees see only their own progress entry.
        Trainers and other roles see all progress entries.
        """
        data = super().to_representation(instance)
        request = self.context.get("request") if self.context else None
        if not request or not getattr(request, "user", None):
            return data

        user = request.user
        role = getattr(getattr(user, "profile", None), "role", None)

        if role == "trainee":
            try:
                user_id = int(user.id)
            except Exception:
                return data
            entries = data.get("progress_entries", []) or []
            data["progress_entries"] = [pe for pe in entries if int(pe.get("trainee") or 0) == user_id]

        return data
