import quart

ALLOWED_USER_PERMISSIONS = ["manage_gallery", "view_gallery"]


def verify_permissions(permissions):
    for perm in permissions:
        if perm.lower() not in ALLOWED_USER_PERMISSIONS:
            return quart.abort(400, description=perm + " is not a valid user permissions")
