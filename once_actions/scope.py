"""Operator-selected application scope; not an operating-system sandbox."""

import ipaddress
from urllib.parse import urlsplit

from .skills import SkillError


def application_origin(url):
    if not isinstance(url, str) or len(url) > 2048:
        raise SkillError("Provide a short application URL")
    try:
        parsed = urlsplit(url)
        port = parsed.port
        host = parsed.hostname
    except ValueError:
        raise SkillError("Invalid application URL") from None
    if not host or parsed.username or parsed.password or parsed.fragment:
        raise SkillError("URL credentials and fragments are not supported")
    if parsed.scheme == "http":
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = False
        if not local or not port:
            raise SkillError("HTTP is limited to literal loopback addresses with a port; otherwise use HTTPS")
    elif parsed.scheme != "https":
        raise SkillError("Use HTTPS or an explicit loopback HTTP address")
    return f"{parsed.scheme}://{parsed.netloc}"


def restrict_context(context, origin, blocked):
    def route(request):
        parts = urlsplit(request.request.url)
        if f"{parts.scheme}://{parts.netloc}" != origin:
            blocked.append("A request left the selected application origin")
            request.abort()
        else:
            request.continue_()

    context.route("**/*", route)
    context.route_web_socket("**/*", lambda socket: socket.close())
