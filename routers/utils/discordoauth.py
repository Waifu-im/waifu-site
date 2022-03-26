from quart import current_app, request, abort, jsonify
from .exceptions import Unauthorized
import urllib


async def fetch_user_safe():
    try:
        return await current_app.discord.fetch_user()
    except:
        raise Unauthorized(origin=urllib.parse.quote(request.url))


async def get_user_info(user_id, jsondata=False):
    """not really related to oauth"""
    resp = await current_app.session.get(
        f"http://127.0.0.1:8033/userinfos/?id={user_id}"
    )
    if resp.status == 404:
        if jsondata:
            response = jsonify(dict(detail="Please provide a valid user_id"))
            response.status_code = 400
            abort(response)
        abort(400, description="Please provide a valid user_id")

    if resp.status != 200:
        if jsondata:
            response = jsonify(
                dict(detail="Sorry, something went wrong with the ipc request.")
            )
            response.status_code = 500
            abort(response)
        abort(500, description="Sorry, something went wrong with the ipc request.")
    return await resp.json()
