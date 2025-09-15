from rest_framework import permissions
import logging

logger = logging.getLogger(__name__)

class IsTrainer(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and getattr(user, "profile", None) and user.profile.role == "trainer")


class IsAssignedOrTrainerOrReadOnly(permissions.BasePermission):
    """
    SAFE_METHODS: allow reading (views may restrict listing).
    For unsafe methods:
      - Trainers: allowed
      - Trainees: allowed only if they are assigned to the object and only for PATCH/PUT (on my_progress)
        and only for allowed fields.
    """
    # allowed trainee fields for partial/put update on progress:
    TRAINEE_ALLOWED_FIELDS = {"status", "report", "deployment_link", "github_link", "completed_at"}

    # keys that may appear in request data but should be ignored for permission checks
    _IGNORED_KEYS = {"csrfmiddlewaretoken"}

    def has_permission(self, request, view):
        # allow list and create to be checked in the view
        return True

    def has_object_permission(self, request, view, obj):
        # Read allowed
        if request.method in permissions.SAFE_METHODS:
            return True

        user = request.user
        if not user or not user.is_authenticated:
            return False

        # Trainers: full access
        if getattr(user, "profile", None) and user.profile.role == "trainer":
            return True

        # For trainees: allow only if they are assigned_to the project
        if user in obj.assigned_to.all():
            # If this is the custom action 'my_progress' on the view: allow PATCH/PUT for trainee
            action = getattr(view, "action", None)
            if action == "my_progress" and request.method in ("PATCH", "PUT"):
                # Defensive: extract keys from request.data (works with QueryDict, dict, MultiPart)
                try:
                    raw_keys = set(request.data.keys())
                except Exception:
                    raw_keys = set()

                keys = set(k for k in raw_keys if k not in self._IGNORED_KEYS)

                # If no keys provided (empty body), deny (or you can allow if you prefer)
                if not keys:
                    logger.debug("Denied my_progress: no updatable keys provided by trainee %s", getattr(user, "username", None))
                    return False

                if keys.issubset(self.TRAINEE_ALLOWED_FIELDS):
                    return True

                # denied: log which unexpected keys were present
                logger.debug(
                    "Denied my_progress update for user=%s, unexpected keys=%s allowed=%s",
                    getattr(user, "username", None),
                    keys - self.TRAINEE_ALLOWED_FIELDS,
                    self.TRAINEE_ALLOWED_FIELDS,
                )
                return False

            # For trainees: other actions on the project not allowed
            return False

        return False
