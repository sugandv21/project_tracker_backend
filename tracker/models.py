from django.db import models
from django.contrib.auth.models import User


class Profile(models.Model):
    ROLE_CHOICES = (
        ("trainee", "Trainee"),
        ("trainer", "Trainer"),
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="trainee")

    def __str__(self):
        return f"{self.user.username} ({self.role})"


class MiniProject(models.Model):
    PRIORITY_CHOICES = (("low", "Low"), ("medium", "Medium"), ("high", "High"))

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    # allow multiple trainees
    assigned_to = models.ManyToManyField(User, related_name="mini_projects")

    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="medium")
    due_date = models.DateField(null=True, blank=True)

    created_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_projects"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.title


class TraineeProgress(models.Model):
    STATUS_CHOICES = (
        ("todo", "To Do"),
        ("inprogress", "In Progress"),
        ("complete", "Complete"),
    )

    trainee = models.ForeignKey(User, on_delete=models.CASCADE, related_name="progress_entries")
    project = models.ForeignKey(MiniProject, on_delete=models.CASCADE, related_name="progress_entries")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="todo")
    report = models.FileField(upload_to="reports/", null=True, blank=True)
    deployment_link = models.URLField(null=True, blank=True)
    github_link = models.URLField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # new: trainer's comment about this trainee's progress/report
    trainer_comment = models.TextField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("trainee", "project")  # one progress per trainee per project

    def __str__(self):
        return f"{self.trainee.username} progress on {self.project.title}"
