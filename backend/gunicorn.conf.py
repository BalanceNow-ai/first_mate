"""Gunicorn configuration for the Helm API (uvicorn ASGI workers).

Every knob comes from the environment so the same image serves local and production:

    WEB_CONCURRENCY            worker processes (default 2)
    GUNICORN_BIND              listen address (default 0.0.0.0:8000)
    GUNICORN_TIMEOUT           hard worker timeout, seconds (default 60)
    GUNICORN_GRACEFUL_TIMEOUT  graceful shutdown, seconds (default 30)
    GUNICORN_KEEPALIVE         keep-alive, seconds (default 5; keep below the proxy's)
    GUNICORN_MAX_REQUESTS      recycle a worker after N requests (default 2000, 0 = off)
    GUNICORN_LOG_LEVEL         error log level (default info)
    FORWARDED_ALLOW_IPS        comma-separated proxy IPs/CIDRs whose X-Forwarded-* headers
                               are trusted (default 127.0.0.1). "*" is refused: client
                               addresses feed the rate limiter and must not be spoofable.

Access logs never contain query strings (tokens, e-mail addresses and search terms
can appear there): the uvicorn access logger is filtered in ``post_worker_init``.
"""

from __future__ import annotations

import logging
import os


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")
workers = _int("WEB_CONCURRENCY", 2)
worker_class = "uvicorn_worker.UvicornWorker"
timeout = _int("GUNICORN_TIMEOUT", 60)
graceful_timeout = _int("GUNICORN_GRACEFUL_TIMEOUT", 30)
keepalive = _int("GUNICORN_KEEPALIVE", 5)
max_requests = _int("GUNICORN_MAX_REQUESTS", 2000)
max_requests_jitter = _int("GUNICORN_MAX_REQUESTS_JITTER", 200)
# Heartbeat files live in shared memory: the container root filesystem is read-only.
worker_tmp_dir = "/dev/shm"

forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
if "*" in [ip.strip() for ip in forwarded_allow_ips.split(",")]:
    raise SystemExit("FORWARDED_ALLOW_IPS='*' is refused; list the reverse proxy network instead")
proxy_allow_ips = forwarded_allow_ips

accesslog = os.environ.get("GUNICORN_ACCESS_LOG", "-")
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
# Used by non-uvicorn workers; %(U)s is the path WITHOUT the query string.
access_log_format = '%(h)s "%(m)s %(U)s %(H)s" %(s)s %(B)s %(M)sms'


class _StripQueryString(logging.Filter):
    """Remove ``?query`` from uvicorn access-log records (args: client, method, path, ...)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path = args[2].split("?", 1)[0]
            record.args = (*args[:2], path, *args[3:])
        return True


def post_worker_init(worker) -> None:  # noqa: ANN001 - gunicorn hook signature
    logging.getLogger("uvicorn.access").addFilter(_StripQueryString())
