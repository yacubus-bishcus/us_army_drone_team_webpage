from functools import wraps
from flask_login import login_required, current_user
from .extensions import login_manager
from flask import abort 

def roles_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                return login_manager.unauthorized()
            return fn(*args, **kwargs)
        return wrapper
    return deco


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if getattr(current_user, "role", "") != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapper
