import os
import urllib
import quart

from routers.utils import Unauthorized
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
    try:
        data = await current_app.discord.callback()
    except:
        current_app.discord.revoke()
        raise Unauthorized(origin=urllib.parse.quote(request.url))
    redirect_to = data.get("redirect", "/")
    session.permanent = True
    return quart.redirect(redirect_to)


@blueprint.route("/logout/")
async def logout():
    current_app.discord.revoke()
    return quart.redirect(quart.url_for("general.home_"))


@blueprint.route("/reset-token/")
@requires_authorization
async def reset_():
    su = request.args.get("user_id")
    user = await fetch_user_safe()
    full_username = str(user)
    username = user.name
    user_id = user.id
    if su and su != str(user_id):
        if not await has_permissions(user.id, "admin"):
            quart.abort(403)
        resp = await current_app.session.get(
            f"http://127.0.0.1:8033/userinfos/?id={su}"
        )
        if resp.status == 404:
            raise quart.abort(400, description="Please provide a valid user_id")

        if resp.status != 200:
            quart.abort(
                500, description="Sorry, something went wrong with the ipc request."
            )

        t = await resp.json()
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
    su = request.args.get("user_id")
    user = await fetch_user_safe()
    user_id = user.id
    if su and su != str(user_id):
        if not await has_permissions(user.id, "admin"):
            quart.abort(403)
        resp = await current_app.session.get(
            f"http://127.0.0.1:8033/userinfos/?id={su}"
        )
        if resp.status == 404:
            raise quart.abort(400, description="Please provide a valid user_id")

        if resp.status != 200:
            quart.abort(
                500, description="Sorry, something went wrong with the ipc request."
            )

        t = await resp.json()
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
    await current_app.waifuclient.fav(user_id=user.id, toggle=image)
    return quart.redirect(quart.url_for("general.preview_") + f"?image={image}")


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
