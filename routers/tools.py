import os
import urllib
import quart
from quart import Response

from routers.utils import Unauthorized, get_user_info
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


@blueprint.route("/authorization/fav/")
async def authorize_fav():
    user = await fetch_user_safe()
    user_id = request.args.get('user_id', type=int)
    if not user_id:
        quart.abort(400)
    if user_id == user.id:
        quart.abort(404, description="The target user id must be different from the current user id")
    data = dict(
        user_id=user_id,
        temp_token=current_app.config["temp_auth_tokens"][user.id],
        permission=["manage_galleries"],
    )
    redirect_uri = request.args.get('redirect_uri')
    if redirect_uri:
        data.update(dict(redirect_uri=redirect_uri))
    infos = current_app.auth_rule.dumps(data)
    return Response(quart.url_for('tools.authorization_callback') + '?infos=' + infos)


@blueprint.route("/authorization/callback/")
async def authorization_callback():
    user = await fetch_user_safe()
    infos = None
    infos = current_app.auth_rule.load(request.args.get('infos'))
    if infos['temp_token'] != current_app.config["temp_auth_tokens"][user.id]:
        quart.abort(403, description="Invalid temporary token.")
    redirect_uri = urllib.parse.unquote(infos['redirect_uri']) if infos.get('redirect_uri') else None
    data = [(infos['user_id'], p, user.id) for p in infos['permissions']]
    await current_app.executemany(
        "INSERT INTO user_permissions(user_id,permission,target_id) VALUES($1,$2,$3) ON CONFLICT DO NOTHING", data)
    if redirect_uri:
        try:
            return quart.redirect(redirect_uri)
        except:
            pass
    quart.redirect(current_app.config["site_url"])


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
async def editfav_():
    image = request.args.get("image")
    if not image:
        return quart.abort(400)
    user = await fetch_user_safe()
    await current_app.waifu_client.fav_toggle(image, user_id=user.id)
    return quart.redirect(quart.url_for("general.preview_", file=os.path.splitext(image)[0]))


@blueprint.route("/delete_image/")
@requires_authorization
@permissions_check("delete_image")
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
@permissions_check("clean_images")
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
