import os
import waifuim

import quart
from quart import Blueprint, render_template, request, current_app, session

from routers.utils import (
    requires_authorization,
    has_permissions,
    create_token,
    permissions_check,
    fetch_user_safe,
)
from secrets import token_urlsafe
from routers.utils import get_user_info

blueprint = Blueprint("general", __name__, template_folder="static/html")


@blueprint.route("/")
async def home_():
    api_offline = False
    try:
        im = await current_app.waifuclient.random(selected_tags=["waifu"], gif=False, is_nsfw=False)
        random_file = (await current_app.waifuclient.random(
            selected_tags=["waifu"],
            is_nsfw=False,
            order_by="FAVOURITES",
        )).split("/")[-1]
    except waifuim.exceptions.APIException as e:
        im = "https://cdn.waifu.im/aa48cd9dc6b64367.jpg"
        random_file = "aa48cd9dc6b64367.jpg"
        api_offline = True if e.status == 503 else None
    async with current_app.pool.acquire() as conn:
        nb_images = (
            await conn.fetchrow(
                "SELECT COUNT(*) FROM Images WHERE not Images.under_review and not Images.hidden"
            )
        )[0]
        nb_request = (await conn.fetchrow("SELECT COUNT(*) FROM api_logs"))[0]
        nb_tags = (await conn.fetchrow("SELECT COUNT(*) FROM Tags"))[0]
    return await render_template(
        "home.html",
        image=im,
        nb_tags=nb_tags,
        nb_request=nb_request,
        nb_images=nb_images,
        randomfile=random_file,
        apioffline=api_offline,
    )


@blueprint.route("/tags/")
async def tags_():
    rt = await current_app.waifuclient.endpoints(full=True)
    return await render_template(
        "tags.html",
        tags=rt
    )


@blueprint.route("/upload/")
async def upload_():
    rt = await current_app.waifuclient.endpoints(full=True)
    return await render_template(
        "upload.html",
        form_upload=quart.url_for("forms.form_upload"),
        tags=rt["tags"],
    )


@blueprint.route("/docs/")
async def docs_():
    rt = await current_app.waifuclient.endpoints()
    return await render_template(
        "documentation.html",
        tags=rt,
    )


@blueprint.route("/dashboard/")
@requires_authorization
async def dashboard_():
    su = request.args.get("user_id")
    user = await fetch_user_safe()
    full_username = str(user)
    username = user.name
    user_id = user.id
    is_admin = await has_permissions(user.id, "admin")
    last_24h_rq = None

    if su and su != str(user_id):
        if not is_admin:
            quart.abort(403)
        t = await get_user_info(su)
        user_id = t.get("id")
        full_username = t.get("full_name")
        username = t.get("name")

    user_secret = token_urlsafe(10)
    async with current_app.pool.acquire() as conn:
        if is_admin:
            last_24h_rq = await conn.fetchval(
                "SELECT COUNT(*) FROM api_logs WHERE date_trunc('day',date)=date_trunc('day',NOW()) and not user_agent=$1",
                current_app.config["waifu_client_user_agent"])
        await conn.execute(
            'INSERT INTO registered_user("id","name","secret") VALUES($1,$2,$3) ON CONFLICT (id) DO UPDATE SET "name"=$2,"secret"=COALESCE("registered_user"."secret",$3)',
            user_id,
            full_username,
            user_secret,
        )
        user_secret = await conn.fetchrow(
            "SELECT secret FROM registered_user WHERE id=$1", user_id
        )
        user_secret = user_secret[0]
        count_images = (
            await conn.fetchrow(
                "SELECT COUNT(*) FROM FavImages WHERE user_id=$1", user_id
            )
        )[0]
    token, user_secret = create_token(user_id, user_secret=user_secret)
    return await render_template(
        "dashboard.html",
        token=token,
        username=username,
        count_images=count_images,
        user_id=str(user_id),
        is_admin=is_admin,
        last_24h_rq=last_24h_rq,
    )


@blueprint.route("/preview/")
async def preview_():
    is_nsfw = False
    in_fav = False
    inprocess = False
    source = None
    tag_names = []
    existed = session.get("upload_existed")
    auth = await current_app.discord.authorized
    image = request.args.get("image")
    if not image:
        quart.abort(404)
    image = image.lower()
    image_name = os.path.splitext(image)[0]
    if auth:
        try:
            user = await current_app.discord.fetch_user()
            args = (image_name, user.id)
        except:
            auth = False
            args = (image_name,)
    else:
        args = (image_name,)
    async with current_app.pool.acquire() as conn:
        rt = await conn.fetch(
            f"""SELECT Images.file, Images.dominant_color,Images.extension, Images.source, Images.is_nsfw,Tags.name, FavImages.user_id FROM Images
                        LEFT JOIN LinkedTags ON LinkedTags.image = Images.file
                        JOIN Tags ON Tags.id = LinkedTags.tag_id
                        LEFT JOIN FavImages ON FavImages.image = Images.file {'AND FavImages.user_id = $2' if auth else ''}
                        WHERE Images.file = $1""",
            *args,
        )
        if not rt:
            quart.abort(404)
        else:
            imf = rt[0].get("file") + rt[0].get("extension")
            dominant_color = rt[0].get("dominant_color")
            if imf != image:
                return quart.redirect(
                    quart.url_for("general.preview_") + f"?image={imf}"
                )
            if auth:
                in_fav = True if rt[0]["user_id"] else False
            for tag in rt:
                if tag["name"] not in tag_names:
                    tag_names.append(tag["name"])
                if tag["is_nsfw"]:
                    is_nsfw = True
            if existed == image_name:
                del session["upload_existed"]
                existed = True
            else:
                existed = False
            fav_button_description = (
                "Remove the image from your Favorites"
                if in_fav
                else "Add the image to your Favorites"
            )
            if source := rt[0].get("source"):
                description = (
                        f"is_nsfw : {str(is_nsfw).lower()}\n\nSource : {source}\n\n" + "Tags : " + ", ".join(tag_names)
                )
            else:
                description = ", ".join(tag_names)
    return await render_template(
        "preview.html",
        source=source,
        image_name=image_name,
        image=image,
        dominant_color=dominant_color,
        in_fav=in_fav,
        inprocess=inprocess,
        is_nsfw=is_nsfw,
        description=description,
        existed=existed,
        fav_button_description=fav_button_description
        if auth
        else "Login to add the image in your Favorite",
        method="toggle" if in_fav else "insert",
    )


@blueprint.route("/manage/")
@requires_authorization
@permissions_check("manage_images")
async def manage_():
    image = request.args.get("image")
    image_name = os.path.splitext(image)[0]
    if not image:
        return quart.abort(404)
    async with current_app.pool.acquire() as conn:
        image_info = await conn.fetch(
            "SELECT Tags.id,Images.source,Images.file,Images.extension,Images.under_review,Images.hidden,Images.is_nsfw FROM Images LEFT JOIN LinkedTags ON LinkedTags.image=Images.file LEFT JOIN Tags ON Tags.id=LinkedTags.tag_id WHERE Images.file=$1",
            image_name,
        )
        if not image_info:
            return quart.abort(404)
        res = await conn.fetchrow(
            "SELECT author_id,description from Reported_images WHERE image=$1",
            image_name,
        )
        if res:
            report_user_id, report_description = res
            report_user_id = int(report_user_id)
        else:
            report_user_id = None
            report_description = None
        filename_db = image_info[0].get("file") + image_info[0].get("extension")
        if filename_db != image:
            return quart.redirect(
                quart.url_for("general.preview_") + f"?image={filename_db}"
            )

        t = await current_app.waifuclient.endpoints(full=True)
    try:
        existed = [int(tag["id"]) for tag in image_info]
    except TypeError:
        existed = []
    if image_info:
        source = image_info[0]["source"]
    else:
        source = None
    return await render_template(
        "manage.html",
        tags=t["public"] + t["private"],
        existed=existed,
        link="https://cdn.waifu.im/" + image,
        image=image,
        source=source,
        form_manage=quart.url_for("forms.forms_manage"),
        report_user_id=report_user_id,
        report_description=report_description,
        is_under_review=image_info[0]["under_review"],
        is_hidden=image_info[0]["hidden"],
        is_nsfw=image_info[0]["is_nsfw"],
    )
