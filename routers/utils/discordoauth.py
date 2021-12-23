from quart import current_app, request
from .exceptions import Unauthorized
import urllib


async def fetch_user_safe():
    try:
        return await current_app.discord.fetch_user()
    except:
        raise Unauthorized(origin=urllib.parse.quote(request.url))
