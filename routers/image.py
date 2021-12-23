import waifuim
import quart
from routers.utils import (
    requires_authorization,
    has_permissions,
    fetch_user_safe,
    db_to_json,
)
from quart import Blueprint, render_template, request, current_app


blueprint = Blueprint("image", __name__, template_folder="static/html")


@blueprint.route("/<typ>/<category>/")
async def all_api_(typ, category, title=None):
    category = category.lower()
    try:
        files = await getattr(current_app.waifuclient, typ)(category, many=True)
    except waifuim.APIException as e:
        if e.status == 404 or e.status == 422:
            quart.abort(404)
        raise e
    except AttributeError:
        quart.abort(404)
    over18 = True if typ == "nsfw" else False
    return await render_template(
        "all_api.html",
        is_nsfw=over18,
        files=list(files),
        type=typ,
        category=category,
        title=title,
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
    if su:
        if await has_permissions(user.id, "access_galleries", None):
            user_id = su
        else:
            quart.abort(403)
    try:
        files = await current_app.waifuclient.fav(user_id=user_id)
    except waifuim.exceptions.APIException as e:
        if e.status == 404:
            return quart.abort(
                404,
                description="Sorry your gallery is empty, you may want to add some by using the bot or click the red heart on the preview page!",
            )
        raise e

    listesfw = []
    listensfw = []
    files = files["images"]
    for im in files:
        listesfw.extend(
            [t for t in im["tags"] if not t in listesfw and not t["is_nsfw"]]
        )
        listensfw.extend([t for t in im["tags"] if not t in listensfw and t["is_nsfw"]])
    tags = dict(sfw=listesfw, nsfw=listensfw)
    return await render_template(
        "image.html",
        files=files,
        start=None,
        is_nsfw=bool(listensfw),
        tags=tags,
        title=None,
    )


@blueprint.route("/top/")
async def top_():
    files = (await current_app.waifuclient.random(top=True, many=True, raw=True))[
        "images"
    ]
    listesfw = []
    listensfw = []
    for im in files:
        listesfw.extend(
            [t for t in im["tags"] if not t in listesfw and not t["is_nsfw"]]
        )
        listensfw.extend([t for t in im["tags"] if not t in listensfw and t["is_nsfw"]])
    tags = dict(sfw=listesfw, nsfw=listensfw)
    return await render_template(
        "image.html",
        files=files,
        start=None,
        is_nsfw=bool(listensfw),
        tags=tags,
        title="Top",
    )


@blueprint.route("/recent/")
async def recent_():
    files = db_to_json(
        await current_app.pool.fetch(
            """
SELECT DISTINCT Q.file,Q.extension,Q.image_id,Q.like,Q.dominant_color,Q.source,Q.uploaded_at,Tags.name,Tags.id,Tags.is_nsfw,Tags.description
FROM (SELECT file,extension,id as image_id, COUNT(FavImages.image) as like,dominant_color,source,uploaded_at
    FROM Images
    LEFT JOIN FavImages ON FavImages.image=Images.file
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
    listesfw = []
    listensfw = []
    for im in files:
        listesfw.extend(
            [t for t in im["tags"] if not t in listesfw and not t["is_nsfw"]]
        )
        listensfw.extend([t for t in im["tags"] if not t in listensfw and t["is_nsfw"]])
    tags = dict(sfw=listesfw, nsfw=listensfw)
    return await render_template(
        "image.html",
        files=files,
        start=None,
        is_nsfw=bool(listensfw),
        tags=tags,
        title="Recent",
    )
