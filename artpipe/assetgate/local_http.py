"""Restrict the write-capable local API to the loopback workbench."""
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from .api import workspace


class LocalAssetAPI:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/assetgate/"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        host = headers.get("host", "")
        origin = headers.get("origin")
        try:
            local = urlsplit(f"//{host}").hostname in {"localhost", "127.0.0.1", "::1", "testserver"}
            trusted = origin is None or urlsplit(origin).netloc == host
        except ValueError:
            local = trusted = False
        if not local or not trusted:
            await JSONResponse({"detail": "请在本机工作台访问资产 API"}, status_code=403)(scope, receive, send)
            return

        if scope["method"] == "POST" and scope["path"] == "/api/assetgate/assets":
            limit = workspace().config["upload"]["max_bytes"] + 64 * 1024
            supplied = headers.get("content-length")
            if supplied and supplied.isdecimal() and int(supplied) > limit:
                await JSONResponse({"detail": "上传文件超出配置的大小限制"}, status_code=413)(scope, receive, send)
                return
            upstream = receive
            count = 0

            async def bounded():
                nonlocal count
                message = await upstream()
                count += len(message.get("body", b""))
                if count > limit:
                    raise HTTPException(413, "上传文件超出配置的大小限制")
                return message

            receive = bounded

        await self.app(scope, receive, send)
