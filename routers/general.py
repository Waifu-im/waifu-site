import os
import waifuim
from werkzeug.datastructures import MultiDict
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
        im = str(await current_app.waifu_client.random(gif=False, is_nsfw=False))
        random_file = str(await current_app.waifu_client.random(
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
        file=im,
        nb_tags=nb_tags,
        nb_request=nb_request,
        nb_images=nb_images,
        random_file=random_file,
        api_offline=api_offline,
    )


@blueprint.route("/tags/")
async def tags_():
    rt = await current_app.waifu_client.endpoints(full=True)
    return await render_template(
        "tags.html",
        tags=rt
    )


@blueprint.route("/upload/")
async def upload_():
    rt = await current_app.waifu_client.endpoints(full=True)
    return await render_template(
        "upload.html",
        form_upload=quart.url_for("forms.form_upload"),
        tags=rt["versatile"] + rt["nsfw"],
    )


@blueprint.route("/docs/")
async def docs_():
    rt = await current_app.waifu_client.endpoints()
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
        result = await conn.fetch(
            "SELECT * FROM user_permissions JOIN registered_user ON registered_user.id = user_permissions.user_id WHERE target_id=$1",
            user_id)
        trusted_users = None
        if result:
            mapping_list = []
            for r in result:
                r = dict(r)
                mapping_list.append((int(r.pop('user_id')), r))
            trusted_users = MultiDict(mapping_list)
    token, user_secret = create_token(user_id, user_secret=user_secret)
    return await render_template(
        "dashboard.html",
        token=token,
        username=username,
        count_images=count_images,
        user_id=str(user_id),
        is_admin=is_admin,
        last_24h_rq=last_24h_rq,
        trusted_users=trusted_users,
    )


@blueprint.route("/preview/", defaults=dict(file=None))
@blueprint.route("/preview/<string:file>/")
async def preview_(file: str):
    if not file:
        f = await current_app.waifu_client.random(is_nsfw='null')
        return quart.redirect(quart.url_for("general.preview_", file=f.file))
    file_parts = os.path.splitext(file.lower())
    file = file_parts[0]
    filename = ''.join(file_parts)
    auth = await current_app.discord.authorized
    args = [file]
    fav = False
    if auth:
        try:
            user = await current_app.discord.fetch_user()
            args.append(user.id)
        except:
            auth = False
    args = tuple(args)
    rt = await current_app.pool.fetch(
        "SELECT Images.file, Images.dominant_color,Images.extension, Images.source, Images.is_nsfw,"
        "Tags.name, FavImages.user_id "
        "FROM Images "
        "LEFT JOIN LinkedTags ON LinkedTags.image = Images.file "
        "JOIN Tags ON Tags.id = LinkedTags.tag_id "
        f"LEFT JOIN FavImages ON FavImages.image = Images.file {'AND FavImages.user_id = $2' if auth else ''} "
        "WHERE Images.file = $1",
        *args,
    )
    if not rt:
        quart.abort(404)
    if rt[0]['file'] != filename:
        return quart.redirect(quart.url_for("general.preview_", file=rt[0]['file']))
    if auth:
        fav = bool(rt[0]["user_id"])
    tags = {t['name'] for t in rt}
    fav_button_text = 'Remove the image from your Favourites' if fav else 'Add the image to your Favourites'
    description = '\n\n'.join(
        [k.capitalize() + ' : ' + v for k, v in dict(source=rt[0].get('source'), tags=', '.join(tags)).items() if v])
    return await render_template(
        "preview.html",
        source=rt[0]['source'],
        file=file,
        filename=rt[0]['file'] + rt[0]['extension'],
        dominant_color=rt[0]["dominant_color"],
        fav=fav,
        is_nsfw=rt[0]['is_nsfw'],
        description=description,
        fav_button_description=fav_button_text if auth else "Login to add the image in your Favorite",
        method="toggle" if fav else "insert",
    )


@blueprint.route("/manage/", defaults=dict(file=None))
@blueprint.route("/manage/<string:file>/")
@requires_authorization
@permissions_check("manage_images")
async def manage_(file):
    if not file:
        f = await current_app.waifu_client.random(is_nsfw='null')
        return quart.redirect(quart.url_for("general.manage_", file=f.file))
    file_parts = os.path.splitext(file.lower())
    file = file_parts[0]
    filename = ''.join(file_parts)
    async with current_app.pool.acquire() as conn:
        image_info = await conn.fetch(
            "SELECT Tags.id as tag_id,Images.source,Images.file,Images.extension,Images.under_review,Images.hidden,Images.is_nsfw FROM Images LEFT JOIN LinkedTags ON LinkedTags.image=Images.file LEFT JOIN Tags ON Tags.id=LinkedTags.tag_id WHERE Images.file=$1",
            file,
        )
        if not image_info:
            return quart.abort(404)
        res = await conn.fetchrow(
            "SELECT author_id,description from Reported_images WHERE image=$1",
            file,
        )
    file_db = image_info[0]["file"]
    if file_db != filename:
        return quart.redirect(
            quart.url_for("general.manage_", file=file_db)
        )
    if res:
        report_user_id, report_description = res
        report_user_id = int(report_user_id)
    else:
        report_user_id = report_description = None

    t = await current_app.waifu_client.endpoints(full=True)
    try:
        existed = [int(tag["tag_id"]) for tag in image_info]
    except TypeError:
        existed = []
    source = image_info[0].get("source")
    return await render_template(
        "manage.html",
        tags=t["versatile"] + t["nsfw"],
        existed=existed,
        link="https://cdn.waifu.im/" + image_info[0]["file"] + image_info[0]["extension"],
        file=file,
        filename=filename,
        source=source,
        form_manage=quart.url_for("forms.forms_manage"),
        report_user_id=report_user_id,
        report_description=report_description,
        is_under_review=image_info[0]["under_review"],
        is_hidden=image_info[0]["hidden"],
        is_nsfw=image_info[0]["is_nsfw"],
    )
