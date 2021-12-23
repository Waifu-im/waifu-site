from quart import Blueprint, render_template

blueprint = Blueprint('info', __name__, template_folder="static/html")


@blueprint.route("/contact/")
async def contact_():
    return await render_template("contact.html")
