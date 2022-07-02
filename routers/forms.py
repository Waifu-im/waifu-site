import asyncio

import asyncpg

import quart
from routers.utils import (
    requires_authorization,
    permissions_check,
    fetch_user_safe,
    TooHighResolution,
    TooLowResolution,
    get_user_info,
)
from quart import Blueprint, render_template, request, current_app

import io
import os
import xxhash

from PIL import Image as ImagePIL
from colorthief import ColorThief
import webcolors

blueprint = Blueprint(
    "forms", __name__, template_folder="static/html", url_prefix="/forms"
)
VERIFIED_UPLOADERS = [508346978288271360]
ALLOWED_EXTENSION = [".png", ".webp", ".gif", ".jpg", ".jpeg"]


def allowed_file(filename):
    ext = os.path.splitext(filename)[1].lower()
    status = ext in ALLOWED_EXTENSION
    if status:
        return ext


def get_res(content, is_gif):
    with ImagePIL.open(io.BytesIO(content)) as img:
        wid, hgt = img.size
    if ((wid > 2000 or hgt > 2000) and is_gif) or (wid > 8000 or hgt > 8000):
        raise TooHighResolution
    elif (wid < 400 and hgt < 200) or ((wid < 800 or hgt < 1000) and not is_gif):
        raise TooLowResolution
    return wid, hgt


def get_dominant(fileobj):
    color_thief = ColorThief(fileobj)
    return webcolors.rgb_to_hex(color_thief.get_color())


async def insert_db(
    fileobj, filename_no_ext, filename, extension, source, is_nsfw, width, height, tags, loop, user=None
):
    dominant_color = await loop.run_in_executor(None, get_dominant, fileobj)
    fileobj.seek(0)
    async with current_app.pool.acquire() as conn:
        async with conn.transaction():

            if user:
                ur = False if user.id in VERIFIED_UPLOADERS else True
                await conn.execute(
                    "INSERT INTO Registered_user(id,name) VALUES($1,$2) ON CONFLICT (id) DO UPDATE SET name=$2",
                    user.id,
                    str(user),
                )

                await conn.execute(
                    "INSERT INTO Images (file,extension,dominant_color,source,under_review,uploader,is_nsfw,width,height) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                    filename_no_ext,
                    extension,
                    str(dominant_color),
                    source,
                    ur,
                    user.id,
                    is_nsfw,
                    width,
                    height
                )
            else:
                await conn.execute(
                    "INSERT INTO Images (file,extension,dominant_color,source,under_review,is_nsfw,width,height) VALUES($1,$2,$3,$4,$5,$6,$7,$8)",
                    filename_no_ext,
                    extension,
                    str(dominant_color),
                    source,
                    True,
                    is_nsfw,
                    width,
                    height,
                )
            for d in tags:
                await conn.execute(
                    "INSERT  INTO LinkedTags (image,tag_id) VALUES($1,$2)",
                    filename_no_ext,
                    d,
                )
            async with current_app.boto3session.client(
                "s3",
                region_name=current_app.config["s3zone"],
                endpoint_url=current_app.config["s3endpoint"],
            ) as s3:
                await s3.upload_fileobj(
                    fileobj,
                    current_app.config["s3bucket"],
                    filename,
                    ExtraArgs={
                        "ContentType": f'image/{extension.replace(".","")}',
                        "ACL": "public-read",
                    },
                )


@blueprint.route("/upload/", methods=["POST"])
async def form_upload():
    if not await current_app.discord.authorized:
        return (
            dict(
                detail=f'Sorry, you must first <a href="/login/" target="_blank">login</a> before uploading a file.'
            ),
            401,
        )
    user = await current_app.discord.fetch_user()
    blacklisted = await current_app.pool.fetchval(
        "SELECT id FROM registered_user WHERE is_blacklisted AND id=$1",
        user.id
    )
    if blacklisted is not None:
        return (
            dict(
                detail='You have been blacklisted from using the discord bot and uploading new images'
            ),
            403,
        )
    loop = asyncio.get_event_loop()
    forms = await request.form
    tags = forms.getlist("tags[]")
    source = forms.get("source")
    is_nsfw = forms.get("is_nsfw") == "true"
    files = await request.files
    file_bytes = files.get("file")
    if not (file_bytes and tags):
        return (
            dict(
                detail="Sorry, the server did not received all the data it needed. Please retry."
            ),
            400,
        )
    extension = allowed_file(file_bytes.filename)
    if not extension:
        return (
            dict(
                detail="Sorry your file extension isn't allowed Please retry with another file."
            ),
            400,
        )
    content = file_bytes.read()
    file_bytes.seek(0)
    file = xxhash.xxh3_64_hexdigest(content)
    filename = file + extension
    if not source or len(source) < 4:
        source = None
    try:
        width, height = await loop.run_in_executor(
            None, get_res, content, True if extension == ".gif" else False
        )
    except TooHighResolution:
        return dict(detail="Sorry, Your image has a too high resolution."), 400
    except TooLowResolution:
        return (
            dict(
                detail='Sorry, Your image has a too low resolution, Please consider using images enlarger such as <a '
                        'href="http://waifu2x.udp.jp/index.fr.html">waifu2x</a>. '
            ),
            400,
        )
    image_preview = quart.url_for('general.preview_',file=file)
    try:
        await insert_db(
            file_bytes,
            file,
            filename,
            extension,
            source,
            is_nsfw,
            width,
            height,
            tags,
            loop,
            user=user,
        )
    except asyncpg.exceptions.UniqueViolationError:
        return (
            dict(
                detail=f'Sorry this picture already exist, you can find it <a href="{image_preview}">here</a>.'
            ),
            409,
        )
    return dict(detail=image_preview)


@blueprint.route("/manage/", methods=["POST"])
@requires_authorization
@permissions_check("manage_images")
async def forms_manage():
    user = await fetch_user_safe()
    temp_file = None
    dominant_color = None
    extension = None
    forms = await request.form
    files_bytes = await request.files
    file_bytes = files_bytes.get("file")
    filename = forms.get("image")
    file = os.path.splitext(filename)[0]
    is_under_review = forms.get("is_under_review") == "true"
    is_nsfw = forms.get("is_nsfw") == "true"
    is_hidden = forms.get("is_hidden") == "true"
    is_reported = forms.get("is_reported") == "true"
    report_user_id = forms.get("report_user_id", type=int) or user.id
    uploader_id = forms.get("uploader_id", type=int)
    report_description = forms.get("report_description")
    tags = forms.getlist("tags[]")
    source = forms.get("source")
    loop = asyncio.get_event_loop()
    width = height = None
    if not source or len(source) < 4:
        source = None
    if file_bytes:
        extension = allowed_file(file_bytes.filename)
        if not extension:
            return (
                dict(
                    detail="Sorry your file extension isn't allowed Please retry with another file.",
                ),
                400,
            )
        content = file_bytes.read()
        temp_file = xxhash.xxh3_64_hexdigest(content)
        temp_filename = temp_file + extension
        try:
            width, height = await loop.run_in_executor(
                None, get_res, content, True if extension == ".gif" else False
            )
        except TooHighResolution:
            return dict(detail="Sorry, Your image has a too high resolution."), 400
        except TooLowResolution:
            return (
                dict(
                    detail='Sorry, Your image has a too low resolution, Please consider using images enlarger such as <a '
                            'href="http://waifu2x.udp.jp/index.fr.html">waifu2x</a>. '
                ),
                400,
            )
        dominant_color = await loop.run_in_executor(None, get_dominant, file_bytes)
        file_bytes.seek(0)

    async with current_app.pool.acquire() as conn:
        async with conn.transaction():
            temp_file = temp_file if file_bytes else file
            if uploader_id:
                u = await get_user_info(uploader_id, jsondata=True)
                full_uploader_name = u.get("full_name")
                await conn.execute(
                    "INSERT INTO Registered_user(id,name) VALUES($1,$2) ON CONFLICT(id) DO UPDATE SET name=$2",
                    uploader_id,
                    full_uploader_name,
                )
            await conn.execute(
                "UPDATE Images SET source=$1,file=COALESCE($2,file),extension=COALESCE($3,extension),"
                "dominant_color=COALESCE($4,dominant_color),under_review=$5,hidden=$6,is_nsfw=$7,"
                "width=COALESCE($8,width), height=COALESCE($9,height), uploader=$10 "
                "WHERE file=$11",
                source if source else None,
                temp_file,
                extension,
                dominant_color,
                is_under_review,
                is_hidden,
                is_nsfw,
                width,
                height,
                uploader_id,
                file,
            )
            await conn.execute("DELETE FROM LinkedTags WHERE image=$1", temp_file)
            for d in tags:
                await conn.execute(
                    "INSERT INTO LinkedTags (image,tag_id) VALUES($1,$2)",
                    temp_file,
                    int(d),
                )
            if is_reported:
                if report_user_id != user.id:
                    t = await get_user_info(report_user_id, jsondata=True)
                    full_username = t.get("full_name")
                else:
                    full_username=str(user)
                await conn.execute(
                    "INSERT INTO Registered_user(id,name) VALUES($1,$2) ON CONFLICT(id) DO UPDATE SET name=$2",
                    report_user_id,
                    full_username,
                )
                await conn.execute(
                    "INSERT INTO Reported_images (image,author_id,description) VALUES($1,$2,$3) ON CONFLICT(image) DO UPDATE SET author_id=$2,description=$3",
                    temp_file,
                    report_user_id,
                    report_description,
                )
            else:
                await conn.execute(
                    "DELETE FROM Reported_images WHERE image=$1", temp_file
                )

            async with current_app.boto3session.client(
                "s3",
                region_name=current_app.config["s3zone"],
                endpoint_url=current_app.config["s3endpoint"],
            ) as s3:
                if file_bytes:
                    await s3.delete_object(
                        Bucket=current_app.config["s3bucket"], Key=filename
                    )
                    await s3.upload_fileobj(
                        file_bytes,
                        current_app.config["s3bucket"],
                        temp_filename,
                        ExtraArgs={
                            "ContentType": f'image/{extension.replace(".","")}',
                            "ACL": "public-read",
                        },
                    )
    return dict(detail=quart.url_for("general.manage_", file=temp_file))
