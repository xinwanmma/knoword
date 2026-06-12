"""请求日志中间件 — 记录每个 API 的耗时、状态码、请求路径。"""

import time
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """记录每个请求的耗时和状态码。"""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        # 处理请求
        response = await call_next(request)

        # 计算耗时
        duration_ms = round((time.time() - start_time) * 1000, 2)

        # 跳过静态资源
        path = request.url.path
        if path.startswith("/docs") or path.startswith("/redoc") or path.endswith((".js", ".css", ".ico")):
            return response

        # 日志级别根据耗时和状态码决定
        status = response.status_code
        method = request.method
        client = request.client.host if request.client else "unknown"

        log_msg = f"{method} {path} {status} {duration_ms}ms [{client}]"

        if status >= 500:
            logger.error(log_msg)
        elif status >= 400:
            logger.warning(log_msg)
        elif duration_ms > 3000:
            logger.warning(f"SLOW {log_msg}")
        else:
            logger.info(log_msg)

        # 添加响应头
        response.headers["X-Process-Time-Ms"] = str(duration_ms)

        return response
