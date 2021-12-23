class Image:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.url = "https://cdn.waifu.im/" + self.file + self.extension

    def __hash__(self):
        return int(self.image_id)

    def __eq__(self, o):
        return o == self.__hash__()


class PartialImage:
    def __init__(self, file, extension):
        self.file = file
        self.extension = extension
        self.filename = self.file + self.extension


class Tags:
    def __init__(self, tag_id, name, is_nsfw, description):
        self.tag_id = int(tag_id)
        self.name = name
        self.is_nsfw = bool(is_nsfw)
        self.description = description

    def __hash__(self):
        return self.tag_id

    def __eq__(self, o):
        return o == self.__hash__()
