from quart_discord import HttpException


class Unauthorized(HttpException):
    def __init__(self, origin=None):
        self.origin = origin


class TooHighResolution(Exception):
    pass


class TooLowResolution(Exception):
    pass
