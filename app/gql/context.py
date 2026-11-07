"""Per-request GraphQL context."""
from dataclasses import dataclass
from typing import Optional

from auth import admin_account_created
from settings import get_settings


@dataclass
class GraphQLContext:
    user: Optional[object]
    can_admin: bool          # a real admin: may write. Fails closed for collaborators.
    can_shop: bool
    # Reads only: admins and collaborators see the admin-only fields (files, stats).
    can_view_admin: bool = False


def sees_admin(ctx) -> bool:
    """Admin-only *reads*: admins and collaborators. Writes check ctx.can_admin."""
    return bool(getattr(ctx, 'can_view_admin', False) or ctx.can_admin)


def build_context(user=None) -> GraphQLContext:
    """Build the GraphQL context for the caller the endpoint's gate already
    resolved (see auth.resolve_shop_caller) - `user` is None for an anonymous
    caller on a public shop, and is never passed at all for the initial-setup
    bypass below.

    When no admin user has been provisioned (initial setup) auth is disabled;
    callers are treated as admin/shop to mirror the rest of the API.
    """
    if not admin_account_created():
        return GraphQLContext(user=None, can_admin=True, can_shop=True, can_view_admin=True)
    public = get_settings()['shop']['public']
    if user is None:
        # No session and no (or failing) Basic Auth - a public shop still reads
        # fine for this caller, same as a file_access route; a private one doesn't.
        return GraphQLContext(user=None, can_admin=False, can_shop=public)
    return GraphQLContext(
        user=user,
        can_admin=bool(user.has_admin_access()),
        can_shop=bool(user.has_shop_access()) or public,
        can_view_admin=bool(user.has_admin_access()) or bool(getattr(user, 'is_collaborator', False)),
    )


def role_key(ctx: GraphQLContext) -> str:
    """Stable string fed into the ETag so caches don't bleed across roles."""
    if sees_admin(ctx):
        return "admin"
    if ctx.can_shop:
        return "shop"
    return "anon"
