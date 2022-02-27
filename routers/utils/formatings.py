import os
from werkzeug.datastructures import MultiDict
from fastapi.encoders import jsonable_encoder
from .types import Tags, Image


def db_to_json(images, tag_mod=False):
    if tag_mod:
        tagmapping = []
        for im in images:
            im = jsonable_encoder(im)
            tagmapping.append(
                (
                    Tags(
                        im.pop("id"),
                        im.pop("name"),
                        im.pop("description"),
                        im.pop("tag_is_nsfw"),
                    ),
                    im,
                )
            )
        tagmapping = MultiDict(tagmapping)
        tags_ = []
        for tag in tagmapping.keys():
            tag_images = tagmapping.getlist(tag.tag_id)
            tag_images = [
                dict(t, **{"url": "https://cdn.waifu.im/" + t["file"] + t["extension"]})
                for t in tag_images
            ]
            tags_.append(dict(vars(tag), **{"images": tag_images}))
        return jsonable_encoder(tags_)
    else:
        imagemapping = []
        for image in images:
            image = jsonable_encoder(image)
            tag = Tags(
                image.pop("id"),
                image.pop("name"),
                image.pop("description"),
                image.pop("tag_is_nsfw"),
            )
            imagemapping.append((Image(**image), tag))
        imagemapping = MultiDict(imagemapping)
        images_list = []
        for im in imagemapping.keys():
            tags = imagemapping.getlist(im.image_id)
            images_list.append(dict(vars(im), **{"tags": tags}))
        return jsonable_encoder(images_list)
