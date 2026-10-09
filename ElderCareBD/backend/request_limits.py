from fastapi.responses import JSONResponse

from image_storage import MAX_IMAGE_BYTES


MAX_PRESCRIPTION_UPLOAD_REQUEST_BYTES = MAX_IMAGE_BYTES + (512 * 1024)


class PrescriptionUploadLimitMiddleware:
    """Apply an in-process cap before FastAPI parses prescription multipart data."""

    def __init__(self, app, max_request_bytes=MAX_PRESCRIPTION_UPLOAD_REQUEST_BYTES):
        self.app = app
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope, receive, send):
        if not self._is_prescription_upload(scope):
            await self.app(scope, receive, send)
            return

        headers = self._headers(scope)
        authorization = headers.get(b"authorization", b"").strip()
        if not authorization.lower().startswith(b"bearer ") or not authorization[7:].strip():
            await JSONResponse(
                status_code=401,
                content={"detail": "Authentication required."},
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
            return

        content_lengths = headers.get(b"content-length")
        if content_lengths is not None:
            try:
                content_length = int(content_lengths)
            except ValueError:
                await self._invalid_length(scope, receive, send)
                return
            if content_length < 0:
                await self._invalid_length(scope, receive, send)
                return
            if content_length > self.max_request_bytes:
                await self._too_large(scope, receive, send)
                return

        received_bytes = 0
        buffered_messages = []
        while True:
            message = await receive()
            buffered_messages.append(message)
            if message.get("type") == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_request_bytes:
                    await self._too_large(scope, receive, send)
                    return
                if not message.get("more_body", False):
                    break
            elif message.get("type") == "http.disconnect":
                break

        message_index = 0

        async def buffered_receive():
            nonlocal message_index
            if message_index < len(buffered_messages):
                message = buffered_messages[message_index]
                message_index += 1
                return message
            return await receive()

        await self.app(scope, buffered_receive, send)

    @staticmethod
    def _is_prescription_upload(scope):
        return (
            scope.get("type") == "http"
            and scope.get("method") == "POST"
            and scope.get("path", "").rstrip("/") == "/prescriptions"
        )

    @staticmethod
    def _headers(scope):
        parsed = {}
        for key, value in scope.get("headers", []):
            lower_key = key.lower()
            if lower_key in parsed and lower_key == b"content-length":
                parsed[lower_key] += b"," + value
            else:
                parsed[lower_key] = value
        return parsed

    @staticmethod
    async def _too_large(scope, receive, send):
        await JSONResponse(
            status_code=413,
            content={"detail": "Prescription upload request is too large."},
        )(scope, receive, send)

    @staticmethod
    async def _invalid_length(scope, receive, send):
        await JSONResponse(
            status_code=400,
            content={"detail": "Invalid Content-Length header."},
        )(scope, receive, send)
