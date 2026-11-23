from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

class CaseInsensitiveModelBackend(ModelBackend):
    """
    Custom authentication backend that supports case-insensitive username lookup
    (e.g. 'Netcom', 'netcom', or 'NETCOM') while preserving password hashing verification.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None

        # First try exact match
        try:
            user = UserModel._default_manager.get(**{UserModel.USERNAME_FIELD: username})
            if user.check_password(password) and self.user_can_authenticate(user):
                return user
        except UserModel.DoesNotExist:
            pass

        # Try case-insensitive match
        try:
            user = UserModel._default_manager.get(**{f"{UserModel.USERNAME_FIELD}__iexact": username})
            if user.check_password(password) and self.user_can_authenticate(user):
                return user
        except (UserModel.DoesNotExist, UserModel.MultipleObjectsReturned):
            matches = UserModel._default_manager.filter(**{f"{UserModel.USERNAME_FIELD}__iexact": username})
            for u in matches:
                if u.check_password(password) and self.user_can_authenticate(u):
                    return u

        # Mitigate timing attacks
        UserModel().set_password(password)
        return None
