import waifuim
import asyncpg
import aioboto3
import json
import aiohttp
import os
import datetime

import quart
from quart import Quart, render_template, request, current_app
from quart_discord import (
    DiscordOAuth2Session,
    exceptions,
)

from werkzeug.exceptions import HTTPException, InternalServerError
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from private.config import (
    DISCORD_CLIENT_ID,
    DISCORD_CLIENT_SECRET,
    DISCORD_BOT_TOKEN,
    CREDENTIALS_PATH,
    API_TOKEN,
    S3_ENDPOINTS,
    S3_BUCKET,
    S3_ZONE,
)
from routers.utils.exceptions import Unauthorized

from routers.forms import blueprint as forms_blueprint
from routers.general import blueprint as general_blueprint
from routers.image import blueprint as image_blueprint
from routers.info import blueprint as info_blueprint
from routers.tools import blueprint as tools_blueprint
from collections import defaultdict
import secrets
from itsdangerous import URLSafeSerializer

app = Quart(__name__, template_folder="static/html/")
PAYPAL_ICON = """<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-paypal" viewBox="0 0 16 16"><path d="M14.06 3.713c.12-1.071-.093-1.832-.702-2.526C12.628.356 11.312 0 9.626 0H4.734a.7.7 0 0 0-.691.59L2.005 13.509a.42.42 0 0 0 .415.486h2.756l-.202 1.28a.628.628 0 0 0 .62.726H8.14c.429 0 .793-.31.862-.731l.025-.13.48-3.043.03-.164.001-.007a.351.351 0 0 1 .348-.297h.38c1.266 0 2.425-.256 3.345-.91.379-.27.712-.603.993-1.005a4.942 4.942 0 0 0 .88-2.195c.242-1.246.13-2.356-.57-3.154a2.687 2.687 0 0 0-.76-.59l-.094-.061ZM6.543 8.82a.695.695 0 0 1 .321-.079H8.3c2.82 0 5.027-1.144 5.672-4.456l.003-.016c.217.124.4.27.548.438.546.623.679 1.535.45 2.71-.272 1.397-.866 2.307-1.663 2.874-.802.57-1.842.815-3.043.815h-.38a.873.873 0 0 0-.863.734l-.03.164-.48 3.043-.024.13-.001.004a.352.352 0 0 1-.348.296H5.595a.106.106 0 0 1-.105-.123l.208-1.32.845-5.214Z"/></svg>"""
app.asgi_app = ProxyHeadersMiddleware(app.asgi_app, trusted_hosts=["127.0.0.1"])
app.config["site_description"] = (
    "An easy to use API that allows you to get waifu pictures from an archive of over 4000 images "
    "and multiple tags!"
)
app.config["temp_auth_tokens"] = defaultdict(lambda: secrets.token_urlsafe(64))
app.config["temp_auth_secret_key"] = secrets.token_urlsafe(64)
app.auth_rule = URLSafeSerializer(current_app.config["temp_auth_secret_key"])
app.config["site_url"] = "https://waifu.im/"
app.config["sitename"] = "WAIFU.IM"
app.config["bot_invite"] = "https://ayane.live/invite/"
app.config["nsfw_cookie"] = "ageverif"
app.config["s3bucket"] = S3_BUCKET
app.config["s3endpoint"] = S3_ENDPOINTS
app.config["s3zone"] = S3_ZONE
app.config["API_token"] = API_TOKEN
app.config["waifu_client_user_agent"] = "APISite"
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
app.config["DISCORD_CLIENT_ID"] = DISCORD_CLIENT_ID
app.config["DISCORD_CLIENT_SECRET"] = DISCORD_CLIENT_SECRET
app.config["DISCORD_BOT_TOKEN"] = DISCORD_BOT_TOKEN
app.config["DISCORD_REDIRECT_URI"] = "https://waifu.im/callback/"
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
app.permanent_session_lifetime = datetime.timedelta(weeks=1)

with open(CREDENTIALS_PATH, "r") as f:
    dt = json.load(f)
    db_user = dt["db_user"]
    db_password = dt["db_password"]
    db_ip = dt["db_ip"]
    db_name = dt["db_name"]
    app.secret_key = dt["secret_key"]

app.register_blueprint(forms_blueprint)
app.register_blueprint(general_blueprint)
app.register_blueprint(image_blueprint)
app.register_blueprint(info_blueprint)
app.register_blueprint(tools_blueprint)


@app.while_serving
async def create_session():
    current_app.discord = discord = DiscordOAuth2Session(app)
    current_app.config = app.config
    app.boto3session = current_app.boto3session = aioboto3.Session()
    app.session = current_app.session = aiohttp.ClientSession()
    app.pool = current_app.pool = await asyncpg.create_pool(
        min_size=5,
        max_size=5,
        user=db_user,
        password=db_password,
        host=db_ip,
        database=db_name,
    )
    app.waifu_client = current_app.waifu_client = waifuim.WaifuAioClient(
        session=app.session,
        appname=app.config["waifu_client_user_agent"],
        token=app.config["API_token"],
    )
    yield
    await app.waifu_client.close()
    await app.pool.close()
    await app.session.close()
    await app.boto3session.close()


@app.context_processor
async def inject_global_infos():
    user = None
    current_url = str(request.url)
    current_path = str(request.path)
    loged = await app.discord.authorized
    if loged:
        try:
            user = await app.discord.fetch_user()
        except:
            loged = False
            user = None

    def format_sidebar(loged, user):
        returning = f"""
<a type="button" href="/" style="color: #fff" class="btn btn-lg {'current' if current_path == '/' else 'heffect'} text-start shadow-none"><span class="bi-house"></span> Home</a>
<button type="button" style="color: #fff" class="btn btn-lg {'current' if current_path in ('/recent/', '/sfw/waifu/', '/nsfw/ero/', '/fav/', '/top/') else 'heffect'} text-start shadow-none" data-bs-toggle="offcanvas" data-bs-target="#images-sidebar" aria-controls="image-sidebarlabel"><span class="bi-images"></span> Images<span class="bi-arrow-return-right float-end"></span></button>
<a type="button" href="/tags/" style="color: #fff" class="btn btn-lg {'current' if current_path == '/tags/' else 'heffect'} text-start shadow-none"><span class="bi-tags"></span> Tags</a>
<a type="button" href="/upload/" style="color: #fff" class="btn btn-lg {'current' if current_path == '/upload/' else 'heffect'} text-start shadow-none"><span class="bi-upload"></span> Upload</a>
<a type="button" href="/docs/" style="color: #fff" class="btn btn-lg {'current' if current_path == '/docs/' else 'heffect'} text-start shadow-none"><span class="bi-book-half"></span> Docs</a>
<button type="button" style="color: #fff" class="btn btn-lg {'current' if current_path in ('/support/', '/contact/') else 'heffect'} text-start shadow-none" data-bs-toggle="offcanvas" data-bs-target="#info-sidebar" aria-controls="info-sidebarlabel">{PAYPAL_ICON} Info & Support Us<span class="bi-arrow-return-right float-end"></span></button>
<a type="button" href="{'/logout/' if loged else '/login/'}" style="color: #fff" class="btn btn-lg heffect text-start shadow-none"><span class="{'bi-box-arrow-right' if loged else 'bi-box-arrow-in-left'}"></span> {'Logout' if loged else 'Login'}</a>

"""
        if loged and user:
            returning += f"""<a type="button" href="/dashboard/" style="color: #fff" class="btn btn-lg {'current' if current_path == '/dashboard/' else 'heffect'} text-start shadow-none"><span class="bi-person-circle"></span> {user.name}</a>"""

        return f"""
<div class="offcanvas offcanvas-start" style="background-color: #272727;" tabindex="-1" id="main-sidebar" data-bs-scroll="false" data-bs-backdrop="false" aria-labelledby="main-sidebarlabel" aria-modal="true" role="dialog">
    <div class="offcanvas-header">
        <button type="button" class="btn-close btn-close-white text-reset" data-bs-dismiss="offcanvas" aria-label="Close"></button>
    </div>
    <div class="offcanvas-body">
        <div class="d-grid gap-2">
            {returning}
        </div>
    </div>
</div>
<div class="offcanvas offcanvas-start" style="background-color: #272727;" tabindex="-1" id="images-sidebar" data-bs-scroll="false" data-bs-backdrop="false" aria-labelledby="images-sidebarlabel" aria-modal="true" role="dialog">
    <div class="offcanvas-header">
        <button type="button" class="btn-close btn-close-white text-reset" data-bs-dismiss="offcanvas" aria-label="Close"></button>
    </div>
    <div class="offcanvas-body">
        <div class="d-grid gap-2">
            <a type="button" href="/random/?is_nsfw=true" style="color: #fff" class="btn btn-lg {'current' if current_path == '/nsfw/ero/' else 'heffect'} text-start shadow-none"><span class="bi-exclamation-lg"></span> NSFW</a>
            <a type="button" href="/fav/" style="color: #fff" class="btn btn-lg {'current' if current_path == '/fav/' else 'heffect'} text-start shadow-none"><span class="bi-heart"></span> Favorite</a>
            <a type="button" href="/random/?order_by=FAVOURITES&is_nsfw=null" style="color: #fff" class="btn btn-lg {'current' if current_path == '/top/' else 'heffect'} text-start shadow-none"><span class="bi-arrow-up-circle"></span> Top</a>
            <a type="button" href="/recent/" style="color: #fff" class="btn btn-lg {'current' if current_path == '/recent/' else 'heffect'} text-start shadow-none"><span class="bi-clock-history"></span> Recent Uploads</a>
        </div>
    </div>
</div>

<div class="offcanvas offcanvas-start" style="background-color: #272727;" tabindex="-1" id="info-sidebar" data-bs-scroll="false" data-bs-backdrop="false" aria-labelledby="info-sidebarlabel" aria-modal="true" role="dialog">
    <div class="offcanvas-header">
        <button type="button" class="btn-close btn-close-white text-reset" data-bs-dismiss="offcanvas" aria-label="Close"></button>
    </div>
    <div class="offcanvas-body">
        <div class="d-grid gap-2">
            <a type="button" class="btn btn-lg heffect text-start {'current' if current_path == '/contact/' else 'heffect'} shadow-none" href="/contact/" style="color: #fff"><span class="bi-telephone-forward"></span> Contact us</a>
            <a type="button" class="btn btn-lg heffect text-start shadow-none" href="https://github.com/Waifu-im/" style="color: #fff" ><span class="bi-github"></span> Github</a>
            <a type="button" class="btn btn-lg heffect text-start shadow-none" href="{app.config['bot_invite']}" style="color: #fff"><span class="bi-discord"></span> Discord Bot</a>
            <a type="button" class="btn btn-lg heffect text-start shadow-none" href="https://paypal.me/arnaudbucolo" style="color: #fff">{PAYPAL_ICON} Support us</a>
        </div>
    </div>
</div>
"""

    def format_metadatas(
            error=False,
            nsfw=False,
            preview=False,
            color="#fec8fa",
            description=app.config["site_description"],
            title=app.config["sitename"].capitalize(),
    ):
        image = app.config["site_url"] + "favicon.ico"
        metadatas = f"""
<meta name="description" content="{app.config['site_description']}"/>
<meta property="og:site_name" content="{app.config['sitename'].lower()}"/>
<meta property="og:title" content="{title}"/>
<meta property="og:description" content="{description}"/>
<meta property="og:url" content="{current_url if not error else app.config['site_url']}"/>
<meta property="og:image" content="{image if not preview or nsfw else preview}"/>
<meta content="{color}" data-react-helmet="true" name="theme-color"/>"""
        if nsfw:
            metadatas += '<meta name="rating" content="adult"/>'
        if preview and not nsfw:
            metadatas += '<meta name="twitter:card" content="summary_large_image"/>'
        return metadatas

    return dict(
        bot_invite=app.config["bot_invite"],
        has_cookie=request.cookies.get(app.config["nsfw_cookie"]),
        NSFW_COOKIE=app.config["nsfw_cookie"],
        site_description=app.config["site_description"],
        format_metadatas=format_metadatas,
        sitename=app.config["sitename"],
        sidebar=format_sidebar(loged, user),
        site_url=app.config["site_url"],
        loged=loged,
        current_url=current_url,
        current_path=current_path,
        user=user,
    )


@app.errorhandler(exceptions.Unauthorized)
@app.errorhandler(Unauthorized)
async def redirect_unauthorized(error):
    return quart.redirect(quart.url_for("tools.login") + f"?redirect={error.origin}")


@app.errorhandler(HTTPException)
async def handle_exception(error):
    custom_name = None
    if error.code == 404:
        if (
                error.description == "The requested URL was not found on the server."
                                     "If you entered the URL manually please check your spelling and try again."
        ):
            error.description = ""
            custom_name = "Are you lost ?"
    return (
        await render_template(
            "errors/dynamic.html",
            description=error.description,
            title=str(error.code) + " " + error.name.capitalize(),
            errorimage="/static/images/sorry.png"
            if error.code != 404
            else "/static/images/areyoulost.png",
            customname=custom_name or error.name.capitalize(),
            loged=await app.discord.authorized,
            code=error.code,
        ),
        error.code,
    )


@app.errorhandler(waifuim.APIException)
async def handle_api_exception(error):
    return await handle_exception(
        InternalServerError(
            description=f"""Sorry an API error hapened, here it is : {error.detail}"""
        )
    )


@app.route("/favicon.ico")
async def favicon():
    return quart.wrappers.response.FileBody("static/images/favicon.png")
