"""与框架无关的安全校验工具。"""

import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import HTTPException


def validate_external_url(url: str) -> None:
    """仅允许公开 HTTP(S) 地址，防止 URL 导入访问本机或内部网络。"""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(400, "URL 必须是有效的 http 或 https 地址")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, None)}
    except socket.gaierror:
        raise HTTPException(400, "无法解析 URL 主机名")
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise HTTPException(400, "禁止访问本机、私有或保留网络地址")
