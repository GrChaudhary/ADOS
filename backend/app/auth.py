"""
Compatibility import point — every router does `from ..auth import
get_current_user`. The real implementation (JWT verification, roles,
User model) lives in backend/app/rbac.py; kept as a separate small module
so routers didn't all need their import path touched twice when RBAC
replaced the old shared-secret-token require_service_auth().
"""

from .rbac import User, get_current_user, require_role  # noqa: F401
