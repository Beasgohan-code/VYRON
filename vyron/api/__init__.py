#  VYRON — professional music API (mounted at /v1 on the bot's own server).
from vyron.api.app import API_VERSION, build_app, register

__all__ = ["API_VERSION", "build_app", "register"]
