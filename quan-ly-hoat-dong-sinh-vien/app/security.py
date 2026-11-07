from functools import wraps
from flask import g, jsonify, session
from .database import get_db


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    user = get_db().execute("SELECT id,username,email,full_name,role,status FROM users WHERE id=?", (user_id,)).fetchone()
    if not user or user["status"] != "active":
        session.clear()
        return None
    return user


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        g.user = current_user()
        if not g.user:
            return jsonify(error="Vui lòng đăng nhập để tiếp tục."), 401
        return fn(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def decorate(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user["role"] not in roles:
                return jsonify(error="Bạn không có quyền thực hiện thao tác này."), 403
            return fn(*args, **kwargs)
        return wrapped
    return decorate

