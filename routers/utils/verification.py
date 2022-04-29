import quart
from quart import current_app

ALLOWED_USER_PERMISSIONS = ["manage_favourites", "view_favourites"]


async def verify_permissions(permissions):
    permissions = [perm.lower() for perm in permissions]
    for perm in permissions:
        if perm not in ALLOWED_USER_PERMISSIONS:
            return quart.abort(400, description=perm + " is not a valid user permissions")
    return await current_app.pool.fetch("SELECT * FROM permissions WHERE name=any($1::varchar[])", permissions)
