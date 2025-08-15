from functools import wraps
from flask_login import current_user
from .extensions import login_manager

def roles_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                return login_manager.unauthorized()
            return fn(*args, **kwargs)
        return wrapper
    return deco
