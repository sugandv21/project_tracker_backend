import logging
import traceback

from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from rest_framework import viewsets, status, generics, filters
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action

from django_filters.rest_framework import DjangoFilterBackend

from .models import MiniProject, TraineeProgress
from .serializers import (
    MiniProjectSerializer,
    UserSerializer,
    TraineeProgressSerializer,
    UserWithRoleSerializer,
)
from .permissions import IsAssignedOrTrainerOrReadOnly, IsTrainer

logger = logging.getLogger(__name__)


class MiniProjectViewSet(viewsets.ModelViewSet):
    """
    ViewSet for MiniProject.

    Important behaviour:
      - serializer is always initialized with context={'request': request}
      - perform_create will save then ensure created_by is set on the saved instance
        (avoids passing unexpected kwargs into serializer.create())
      - create() will return traceback JSON when DEBUG=True to help local debugging
    """
    queryset = MiniProject.objects.all()
    serializer_class = MiniProjectSerializer
    permission_classes = [IsAssignedOrTrainerOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["priority", "due_date", "assigned_to"]
    search_fields = ["title", "description"]
    ordering_fields = ["due_date", "priority", "created_at"]

    def get_permissions(self):
        # Trainers can create/update/delete full projects
        if self.action in ("create", "destroy", "update", "partial_update"):
            return [IsTrainer()]
        return super().get_permissions()

    def get_queryset(self):
        """
        - Trainers: see all projects.
        - Trainees: see only projects assigned to them.
        Support ?status=<status> to filter by progress status:
          - For trainer: projects that have any progress entry with that status.
          - For trainee: projects where that trainee's progress has that status.
        """
        user = self.request.user
        if not user or not user.is_authenticated:
            return MiniProject.objects.none()

        is_trainer = getattr(user, "profile", None) and getattr(user.profile, "role", None) == "trainer"
        qs = MiniProject.objects.all() if is_trainer else MiniProject.objects.filter(assigned_to=user)

        # optional status filter
        status_filter = self.request.query_params.get("status")
        if status_filter:
            if is_trainer:
                qs = qs.filter(progress_entries__status=status_filter)
            else:
                qs = qs.filter(progress_entries__status=status_filter, progress_entries__trainee=user)

        return qs.distinct()

    def perform_create(self, serializer):
        """
        Save serializer then ensure created_by is set.
        We avoid passing created_by into serializer.save() to prevent signature mismatch
        with serializer.create().
        """
        obj = serializer.save()  # serializer.create handles M2M assigned_to as implemented in serializer
        # If created_by was not set by serializer, set it now and save again.
        try:
            if getattr(obj, "created_by", None) is None and getattr(self.request, "user", None) and self.request.user.is_authenticated:
                obj.created_by = self.request.user
                obj.save()
        except Exception:
            # If saving created_by fails, log and re-raise so create() can catch and return useful info during DEBUG.
            logger.exception("Failed to set created_by on MiniProject (id=%s)", getattr(obj, "id", None))
            raise

    def create(self, request, *args, **kwargs):
        """
        Override create to:
         - pass request into serializer context
         - catch exceptions and log full traceback
         - return traceback in response when DEBUG=True (local debugging only)
        """
        logger.debug("MiniProject.create called by user=%s payload=%s", getattr(request.user, "id", None), request.data)

        serializer = self.get_serializer(data=request.data, context={"request": request})
        try:
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error("Error creating MiniProject (user=%s): %s\n%s", getattr(request.user, "id", None), str(exc), tb)

            if getattr(settings, "DEBUG", False):
                # Helpful for local debugging — do not enable in production.
                return Response({
                    "detail": "Server error while creating MiniProject.",
                    "error": str(exc),
                    "traceback": tb,
                    "payload": request.data,
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            return Response({"detail": "An unexpected error occurred while creating the project."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(
        detail=True,
        methods=["get", "patch", "put"],
        url_path="my_progress",
        url_name="my_progress",
        serializer_class=TraineeProgressSerializer,
    )
    def my_progress(self, request, pk=None):
        """
        GET: return this user's progress for the project (create if absent).
        PATCH/PUT: allow assigned trainee to update their own progress (and accept client-sent completed_at).
        """
        project = self.get_object()
        user = request.user

        # ensure user is assigned
        if user not in project.assigned_to.all():
            return Response({"detail": "Not assigned to this project."}, status=status.HTTP_403_FORBIDDEN)

        progress, _ = TraineeProgress.objects.get_or_create(trainee=user, project=project)

        if request.method in ("PATCH", "PUT"):
            partial = request.method == "PATCH"
            serializer = self.get_serializer(progress, data=request.data, partial=partial, context={"request": request})
            serializer.is_valid(raise_exception=True)
            updated = serializer.save()

            # Persist client-sent completed_at if provided (support ISO and datetime-local)
            client_completed = request.data.get("completed_at")
            if client_completed:
                parsed = parse_datetime(client_completed)
                if parsed is None:
                    # try normalization for 'YYYY-MM-DDTHH:MM'
                    try:
                        if isinstance(client_completed, str) and len(client_completed) == 16:
                            client_completed = client_completed + ":00"
                        parsed = parse_datetime(client_completed)
                    except Exception:
                        parsed = None
                if parsed:
                    updated.completed_at = parsed
                    updated.save()
            else:
                # if status became 'complete' and completed_at is empty, set now
                if updated.status == "complete" and not updated.completed_at:
                    updated.completed_at = timezone.now()
                    updated.save()

            return Response(self.get_serializer(updated, context={"request": request}).data)

        # GET
        return Response(self.get_serializer(progress, context={"request": request}).data)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsTrainer], url_path="comment")
    def comment(self, request, pk=None):
        """
        Trainer posts a comment on a trainee's progress for this project.

        Expected body: { "trainee": <user_id>, "comment": "..." }
        Returns: updated TraineeProgress serialized.
        """
        project = self.get_object()
        user = request.user

        # only trainers reach this because of permission_classes, but keep defensive check
        if not (getattr(user, "profile", None) and getattr(user.profile, "role", None) == "trainer"):
            return Response({"detail": "Only trainers may post comments."}, status=status.HTTP_403_FORBIDDEN)

        trainee_id = request.data.get("trainee")
        comment_text = (request.data.get("comment") or "").strip()

        if not trainee_id or not comment_text:
            return Response({"detail": "Provide both trainee (id) and comment."}, status=status.HTTP_400_BAD_REQUEST)

        # ensure trainee exists
        try:
            trainee = User.objects.get(pk=trainee_id)
        except User.DoesNotExist:
            return Response({"detail": "Trainee not found."}, status=status.HTTP_404_NOT_FOUND)

        if trainee not in project.assigned_to.all():
            return Response({"detail": "Trainee is not assigned to this project."}, status=status.HTTP_400_BAD_REQUEST)

        # get or create progress entry for that trainee
        progress, created = TraineeProgress.objects.get_or_create(trainee=trainee, project=project)

        # set the trainer comment and save
        progress.trainer_comment = comment_text
        progress.save()

        serializer = TraineeProgressSerializer(progress, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # return user including role for frontend convenience
        return Response(UserWithRoleSerializer(request.user).data)


class UserListView(generics.ListAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
