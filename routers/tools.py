import os
import urllib
import json
import quart
from quart import Response
import secrets
from routers.utils import Unauthorized, get_user_info, verify_permissions
from routers.utils import (
    requires_authorization,
    has_permissions,
    permissions_check,
    create_token,
    fetch_user_safe,
)
from quart import Blueprint, render_template, request, current_app, session

blueprint = Blueprint("tools", __name__, template_folder="static/html")


@blueprint.route("/api/")
async def api_redirect():
    return quart.redirect("https://api.waifu.im")


@blueprint.route("/login/")
async def login():
    redirect = request.args.get("redirect")
    if not redirect:
        redirect = "/"
    else:
        redirect = urllib.parse.unquote(redirect)
    return await current_app.discord.create_session(
        scope=["identify"], data=dict(redirect=redirect)
    )


@blueprint.route("/callback/")
async def callback():
    data = None
    try:
        data = await current_app.discord.callback()
        redirect_to = data.get("redirect", "/")
        session.permanent = True
    except:
        current_app.discord.revoke()
        redirect_to = current_app.config["site_url"]
    return quart.redirect(redirect_to)


@blueprint.route("/logout/")
async def logout():
    current_app.discord.revoke()
    return quart.redirect(quart.url_for("general.home_"))


@blueprint.route("/authorization/")
@blueprint.route("/authorization/revoke/", defaults={'revoke': True})
@requires_authorization
async def authorize_(revoke=False):
    user = await fetch_user_safe()
    temp_auth_tokens = json.loads(await current_app.redis.get('temp_auth_tokens'))
    permissions = request.args.getlist('permissions')
    data = dict(
        state=temp_auth_tokens.setdefault(user.id, secrets.token_urlsafe(20)),
        user_id=request.args.get('user_id', type=int),
        permissions=permissions if permissions else None,
        revoke=revoke,
    )
    missing = [k for k, v in data.items() if v is None]
    if missing:
        return quart.abort(
            400,
            description="One of the following parameters were missing or of the wrong type : " + ", ".join(missing)
        )
    if data['user_id'] == user.id:
        quart.abort(400, description="The target user id must be different from the current user id")
    verify_permissions(data['permissions'])
    await get_user_info(data['user_id'], jsondata=True)
    redirect_uri = request.args.get('redirect_uri')
    if redirect_uri:
        data.update(dict(redirect_uri=redirect_uri))
    data = urllib.parse.urlencode(data, True)
    await current_app.redis.set('temp_auth_tokens', json.dumps(temp_auth_tokens))
    return Response(current_app.config['site_url'] + quart.url_for('tools.authorization_callback') + data)


@blueprint.route("/authorization/callback/")
@requires_authorization
async def authorization_callback():
    user = await fetch_user_safe()
    data = dict(
        state=request.args.get('state'),
        user_id=request.args.get('user_id', int),
        permissions=list(request.args.getlist('permissions')),
        revoke=request.args.get('revoke', bool)
    )
    missing = [k for k, v in data.items() if not v]
    if missing:
        return quart.abort(
            400,
            description="One of the following parameters were missing or of the wrong type : " + ", ".join(missing)
        )

    temp_auth_tokens = json.loads(await current_app.redis.get('temp_auth_tokens'))
    verify_permissions(data['permissions'])
    await get_user_info(data['user_id'], jsondata=True)
    if data['state'] != temp_auth_tokens.get(str(user.id)):
        quart.abort(403, description="Invalid temporary token.")
    temp_auth_tokens.pop(str(user.id), None)
    await current_app.redis.set('temp_auth_tokens', json.dumps(temp_auth_tokens))
    redirect_uri = urllib.parse.unquote(request.args['redirect_uri']) if request.args.get('redirect_uri') else None
    vals = [(data['user_id'], p, user.id) for p in data['permissions']]
    if data['revoke']:
        await current_app.pool.executemany(
            "DELETE FROM user_permissions WHERE user_id=$1 and permission=$2 and target_id=$3", vals)
    else:
        await current_app.pool.executemany(
            "INSERT INTO user_permissions(user_id,permission,target_id) VALUES($1,$2,$3) ON CONFLICT DO NOTHING", vals)
    return quart.redirect(redirect_uri if redirect_uri else current_app.config["site_url"])


@blueprint.route("/reset-token/")
@requires_authorization
async def reset_():
    su = request.args.get("user_id", type=int)
    user = await fetch_user_safe()
    full_username = str(user)
    username = user.name
    user_id = user.id
    if su and su != user_id:
        if not await has_permissions(user.id, "admin"):
            quart.abort(403)

        t = await get_user_info(su)
        user_id = t.get("id")
        full_username = t.get("full_name")
        username = t.get("name")
    token, user_secret = create_token(user_id)
    await current_app.pool.execute(
        "INSERT INTO registered_user(id,name,secret) VALUES($1,$2,$3) ON CONFLICT (id) DO UPDATE SET name=$2,secret=$3",
        user_id,
        str(full_username),
        user_secret,
    )

    return quart.redirect(quart.url_for("general.dashboard_") + f"?user_id={user_id}")


@blueprint.route("/purge-gallery/")
@requires_authorization
async def purge_gallery_():
    su = request.args.get("user_id", type=int)
    user = await fetch_user_safe()
    user_id = user.id
    if su and su != user_id:
        if not await has_permissions(user.id, "admin"):
            quart.abort(403)
        t = await get_user_info(su)
        user_id = t.get("id")

    await current_app.pool.execute(
        "DELETE FROM FavImages WHERE user_id=$1",
        user_id,
    )

    return quart.redirect(quart.url_for("general.dashboard_") + f"?user_id={user_id}")


@blueprint.route("/toggle-image/")
@requires_authorization
async def edit_favourites():
    image = request.args.get("image")
    if not image:
        return quart.abort(400)
    user = await fetch_user_safe()
    await current_app.waifu_client.fav_toggle(image, user_id=user.id)
    return quart.redirect(quart.url_for("general.preview_", file=os.path.splitext(image)[0]))


@blueprint.route("/delete_image/")
@requires_authorization
@permissions_check("manage_images")
async def delete_image():
    image = request.args.get("image").lower()
    image_name = os.path.splitext(image)[0]

    if not image:
        quart.abort(400)
    async with current_app.pool.acquire() as conn:
        await conn.execute("DELETE FROM Images WHERE file=$1", image_name)
    async with current_app.boto3session.client(
            "s3",
            region_name=current_app.config["s3zone"],
            endpoint_url=current_app.config["s3endpoint"],
    ) as s3:
        await s3.delete_object(Bucket=current_app.config["s3bucket"], Key=image)
    return quart.redirect(f"https://waifu.im/list/")


@blueprint.route("/list/")
@requires_authorization
@permissions_check("admin")
async def list_():
    async with current_app.pool.acquire() as conn:
        t = await conn.fetch(
            "SELECT Images.id, Images.file,Images.extension FROM LinkedTags JOIN Images ON Images.file=LinkedTags.image JOIN Tags ON Tags.id=LinkedTags.tag_id WHERE Tags.name='hentai'"
        )
    image = [{"id": im["id"], "file": im["file"] + im["extension"]} for im in t]
    image = sorted(image, key=lambda k: k["id"])
    return await render_template("list.html", files=image)


@blueprint.route("/rmv/")
@requires_authorization
@permissions_check("manage_images")
async def im():
    image = request.args.get("image")
    user = await fetch_user_safe()
    async with current_app.pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM LinkedTags WHERE image=$1 and tag_id=4",
            os.path.splitext(image)[0],
        )
        await conn.execute(
            "INSERT INTO LinkedTags VALUES($1,$2) ON CONFLICT DO NOTHING",
            os.path.splitext(image)[0],
            2,
        )
    print(f"{user} deleted the hentai tag and added the ecchi tag for the file {image}")
    return quart.redirect("https://waifu.im/list/")


@blueprint.route("/clean/")
@requires_authorization
@permissions_check("manage_images")
async def clean_images():
    async with current_app.pool.acquire() as conn:
        async with conn.transaction():
            dupes1 = []
            dupes2 = []
            raw_db_image_list = await conn.fetch("SELECT file, extension FROM Images")
            db_image_list = [im[0] + im[1] for im in raw_db_image_list]
            async with current_app.boto3session.resource(
                    "s3",
                    region_name=current_app.config["s3zone"],
                    endpoint_url=current_app.config["s3endpoint"],
            ) as s3:
                bucket = await s3.Bucket(current_app.config["s3bucket"])
                s3_image_list = [file.key async for file in bucket.objects.all()]

            for it in s3_image_list:
                if it not in db_image_list:
                    try:
                        async with current_app.boto3session.client(
                                "s3",
                                region_name=current_app.config["s3zone"],
                                endpoint_url=current_app.config["s3endpoint"],
                        ) as s3:
                            await s3.delete_object(
                                Bucket=current_app.config["s3bucket"], Key=it
                            )
                        dupes2.append(it)
                    except:
                        continue
            for image in db_image_list:
                if image not in s3_image_list:
                    dupes1.append((os.path.splitext(image)[0],))
            await conn.executemany("DELETE FROM Images WHERE file=$1", dupes1)
    return f"I deleted the following files from the database: {dupes1} | From the storage : {dupes2}"
