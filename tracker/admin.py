from django.contrib import admin
from .models import Profile, MiniProject, TraineeProgress


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role")
    list_filter = ("role",)


@admin.register(MiniProject)
class MiniProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "priority", "due_date", "created_by", "created_at")
    list_filter = ("priority", "due_date")
    search_fields = ("title", "description")
    filter_horizontal = ("assigned_to",)


@admin.register(TraineeProgress)
class TraineeProgressAdmin(admin.ModelAdmin):
    list_display = ("trainee", "project", "status", "updated_at", "completed_at", "trainer_comment")
    list_filter = ("status", "updated_at", "completed_at")
    search_fields = ("project__title", "trainee__username", "trainer_comment")
