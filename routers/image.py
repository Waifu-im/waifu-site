import waifuim
import quart
from routers.utils import (
    requires_authorization,
    has_permissions,
    fetch_user_safe,
    db_to_json,
    permissions_check,
)
from quart import Blueprint, render_template, request, current_app

blueprint = Blueprint("image", __name__, template_folder="static/html")


@blueprint.route("/random/")
async def all_api_(title=None):
    full = request.args.get('full', None)
    is_nsfw = request.args.get('is_nsfw', type=bool)
    selected_tags = request.args.getlist('selected_tags')
    order_by = request.args.get('order_by', None)
    if full:
        try:
            user = await current_app.discord.fetch_user()
            full = await has_permissions(user.id, "admin")
        except:
            full = None
    try:
        files = await current_app.waifuclient.random(
            is_nsfw=is_nsfw,
            selected_tags=selected_tags,
            excluded_tags=request.args.getlist('excluded_tags'),
            full=full,
            order_by=order_by,
            many=None if full else True,

        )
    except waifuim.APIException as e:
        if e.status == 404 or e.status == 422:
            quart.abort(404)
        raise e
    except AttributeError:
        return quart.abort(404)
    category_name = selected_tags[0] if len(selected_tags) == 1 else 'Top' if order_by == 'FAVOURITES' else 'NSFW' if is_nsfw else 'Random'
    tags = []
    is_nsfw = False
    for im in files:
        if im["is_nsfw"]:
            is_nsfw = True
        tags.extend(
            [t for t in im["tags"] if t not in tags]
        )
    if category_name == 'Random' or category_name == 'Top':
        return await render_template(
            "image.html",
            files=files,
            start=None,
            is_nsfw=is_nsfw,
            tags=tags,
            title=category_name,
            href_url=quart.url_for("general.preview_"),
        )
    return await render_template(
        "all_api.html",
        is_nsfw=is_nsfw,
        files=list(files),
        type=typ,
        category=category_name,
        title=title,
        href_url=quart.url_for("general.preview_"),
    )

@blueprint.route("/fav/")
@requires_authorization
async def fav_():
    user = await fetch_user_safe()
    su = request.args.get("user_id")
    try:
        su = int(su)
    except:
        su = None
    user_id = user.id
    if su and su != user_id:
        if await has_permissions(user.id, "access_galleries"):
            user_id = su
        else:
            quart.abort(403)
    try:
        files = (await current_app.waifuclient.fav(user_id=user_id))["images"]
    except waifuim.exceptions.APIException as e:
        if e.status == 404:
            return quart.abort(
                404,
                description="Sorry your gallery is empty, you may want to add some by using the bot or click the red heart on the preview page!",
            )
        raise e
    tags = []
    is_nsfw = False
    for im in files:
        if im['is_nsfw']:
            is_nsfw = True
        tags.extend(
            [t for t in im["tags"] if t not in tags]
        )
    return await render_template(
        "image.html",
        files=files,
        start=None,
        is_nsfw=is_nsfw,
        tags=tags,
        title=None,
        href_url=quart.url_for("general.preview_"),
    )


@blueprint.route("/top/")
async def top_():
    files = (await current_app.waifuclient.random(top=True, many=True, raw=True))[
        "images"
    ]
    tags = []
    is_nsfw = False
    for im in files:
        if im['is_nsfw']:
            is_nsfw = True
        tags.extend(
            [t for t in im["tags"] if t not in tags]
        )
    return await render_template(
        "image.html",
        files=files,
        start=None,
        is_nsfw=is_nsfw,
        tags=tags,
        title="Top",
        href_url=quart.url_for("general.preview_"),
    )


@blueprint.route("/recent/")
async def recent_():
    files = db_to_json(
        await current_app.pool.fetch(
            """
SELECT DISTINCT Q.file,Q.extension,Q.image_id,Q.uploaded_at,Tags.name,Tags.id,Tags.is_nsfw,Tags.description
FROM (SELECT file,extension,id as image_id,uploaded_at
    FROM Images
    WHERE not Images.under_review
    GROUP BY Images.file
    ORDER BY uploaded_at DESC
    LIMIT 60
    ) AS Q
JOIN LinkedTags ON LinkedTags.image=Q.file
JOIN Tags ON Tags.id=LinkedTags.tag_id
ORDER BY Q.uploaded_at DESC"""
        )
    )
    tags = []
    is_nsfw = False
    for im in files:
        if im['is_nsfw']:
            is_nsfw = True
        tags.extend(
            [t for t in im["tags"] if t not in tags]
        )
    return await render_template(
        "image.html",
        files=files,
        start=None,
        is_nsfw=is_nsfw,
        tags=tags,
        title="Recent",
        href_url=quart.url_for("general.preview_"),
    )


@blueprint.route("/report/")
@requires_authorization
@permissions_check("admin")
async def report_():
    files = db_to_json(
        await current_app.pool.fetch(
            """
SELECT DISTINCT Images.file,Images.extension,Images.id AS image_id,Images.uploaded_at,Tags.name,Tags.id,Tags.is_nsfw,Tags.description
FROM Images
JOIN Reported_images ON Reported_images.image=Images.file
JOIN LinkedTags ON LinkedTags.image=Images.file
JOIN Tags ON Tags.id=LinkedTags.tag_id
ORDER BY uploaded_at DESC"""
        )
    )
    tags = []
    is_nsfw = False
    for im in files:
        if im['is_nsfw']:
            is_nsfw = True
        tags.extend(
            [t for t in im["tags"] if t not in tags]
        )
    if not tags:
        return quart.abort(
            404,
            description="Sorry there is no reported image.",
        )
    return await render_template(
        "image.html",
        files=files,
        start=None,
        is_nsfw=is_nsfw,
        tags=tags,
        title="Report",
        href_url=quart.url_for("general.manage_"),
    )


@blueprint.route("/review/")
@requires_authorization
@permissions_check("admin")
async def review_():
    files = db_to_json(
        await current_app.pool.fetch(
            """
SELECT DISTINCT Images.file,Images.extension,Images.id AS image_id,Images.uploaded_at,Images.is_nsfw, Tags.name,Tags.id,Tags.description
FROM Images
JOIN LinkedTags ON LinkedTags.image=Images.file
JOIN Tags ON Tags.id=LinkedTags.tag_id
WHERE Images.under_review
ORDER BY uploaded_at DESC"""
        )
    )
    tags = []
    is_nsfw = False
    for im in files:
        if im['is_nsfw']:
            is_nsfw = True
        tags.extend(
            [t for t in im["tags"] if t not in tags]
        )
    if not tags:
        return quart.abort(
            404,
            description="Sorry there is no image under review.",
        )
    return await render_template(
        "image.html",
        files=files,
        start=None,
        is_nsfw=is_nsfw,
        tags=tags,
        title="Review",
        href_url=quart.url_for("general.manage_"),
    )
