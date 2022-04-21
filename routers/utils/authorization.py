from quart import abort, current_app, request
from .exceptions import Unauthorized
from .discordoauth import fetch_user_safe
from secrets import token_urlsafe
from itsdangerous import URLSafeSerializer
import urllib
import functools


async def has_permissions(user_id, perm_name):
    authorized = await current_app.pool.fetchrow(
        """SELECT * FROM user_permissions
JOIN permissions ON permissions.name=user_permissions.permission
JOIN registered_user ON registered_user.id=user_permissions.user_id
WHERE registered_user.id=$1 and (permissions.name=$2 or permissions.position > (SELECT position from permissions where name=$2) or permissions.name='admin') and target_id is NULL""",
        user_id,
        perm_name,
    )
    return True if authorized else False


def requires_authorization(view):
    """A decorator for quart views which raises exception :py:class:`quart_discord.Unauthorized` if the user
    is not authorized from Discord OAuth2.
    """

    @functools.wraps(view)
    async def wrapper(*args, **kwargs):
        if not await current_app.discord.authorized:
            raise Unauthorized(origin=urllib.parse.quote(request.url))
        return await view(*args, **kwargs)

    return wrapper


def permissions_check(perm_name):
    def wrapper(view):
        @functools.wraps(view)
        async def decorator(*args, **kwargs):
            user = await fetch_user_safe()
            if not await has_permissions(user.id, perm_name.lower()):
                abort(403)
            return await view(*args, **kwargs)

        return decorator

    return wrapper


def create_token(user_id, user_secret=None):
    if not user_secret:
        user_secret = token_urlsafe(10)
    rule = URLSafeSerializer(current_app.secret_key)
    return rule.dumps({"id": int(user_id), "secret": user_secret}), user_secret
