"""Validasi, perakitan, dan penyamaran URL RTSP.

URL kamera sering memuat kredensial (rtsp://user:sandi@host/...). Kredensial
tidak boleh sampai ke HTML, JSON, atau log: gunakan `mask_url` / `redact_text`
untuk apa pun yang akan ditampilkan.
"""
import ipaddress
import re
import socket
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

ALLOWED_SCHEMES = ("rtsp", "rtsps")
MASK = "••••"
MAX_URL_LENGTH = 500

_BLOCKED_HOSTNAMES = {"metadata.google.internal"}
_SECRET_QUERY_KEYS = re.compile(r"pass|pwd|token|key|secret|auth", re.I)
_USERINFO_RE = re.compile(r"(rtsps?://[^:/@\s]*):[^@\s]*@", re.I)


class RtspUrlError(ValueError):
    """Pesan sudah dalam bahasa pengguna dan aman ditampilkan."""


def split_rtsp_url(raw):
    """Pecah dan validasi URL RTSP. Raise RtspUrlError bila tidak valid."""
    raw = (raw or "").strip()
    if not raw:
        raise RtspUrlError("URL RTSP wajib diisi.")
    if len(raw) > MAX_URL_LENGTH:
        raise RtspUrlError(f"URL terlalu panjang (maksimum {MAX_URL_LENGTH} karakter).")
    if re.search(r"\s", raw):
        raise RtspUrlError("URL tidak boleh mengandung spasi.")

    try:
        parts = urlsplit(raw)
    except ValueError:
        raise RtspUrlError("Format URL tidak valid.") from None

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise RtspUrlError("URL harus diawali rtsp:// atau rtsps://.")

    try:
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise RtspUrlError("Port pada URL tidak valid.") from None

    if not host:
        raise RtspUrlError("Alamat host kamera tidak ditemukan di URL.")
    if port is not None and not 1 <= port <= 65535:
        raise RtspUrlError("Port pada URL tidak valid.")

    _check_host(host)
    return parts


def _check_host(host):
    """Tolak tujuan yang jelas berbahaya (mis. endpoint metadata cloud)."""
    if host.lower() in _BLOCKED_HOSTNAMES:
        raise RtspUrlError("Alamat host tidak diizinkan.")

    address = None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Bentuk IPv4 tak lazim ("2852039166", "0xA9FEA9FE", "169.254.43518")
        # tetap diterjemahkan resolver OS menjadi IP, jadi normalkan dulu.
        try:
            address = ipaddress.ip_address(socket.inet_ntoa(socket.inet_aton(host)))
        except (OSError, ValueError):
            return  # nama host biasa

    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
        raise RtspUrlError("Alamat host tidak diizinkan.")


def build_rtsp_url(raw_url, username="", password=""):
    """Gabungkan username/password terpisah ke URL (di-encode dengan benar).

    Kolom terpisah lebih aman daripada menempel sandi mentah di URL, karena
    karakter seperti @ : / # pada sandi akan merusak URL.
    """
    parts = split_rtsp_url(raw_url)
    username = (username or "").strip()
    password = password or ""

    if not username:
        if password:
            raise RtspUrlError("Isi username bila memakai password.")
        return raw_url.strip()
    if parts.username is not None:
        raise RtspUrlError(
            "URL sudah memuat kredensial. Hapus dari URL atau kosongkan kolom username/password."
        )
    if "\n" in password or "\r" in password:
        raise RtspUrlError("Password tidak valid.")

    userinfo = quote(username, safe="")
    if password:
        userinfo += ":" + quote(password, safe="")
    return urlunsplit((parts.scheme, f"{userinfo}@{parts.netloc}", parts.path, parts.query, parts.fragment))


def mask_url(url):
    """Samarkan sandi (dan nilai query rahasia) untuk ditampilkan."""
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return f"rtsp://{MASK}"

    netloc = parts.netloc
    if "@" in netloc:
        userinfo, _, hostport = netloc.rpartition("@")
        user, has_password, _ = userinfo.partition(":")
        netloc = f"{user}:{MASK}@{hostport}" if has_password else f"{user}@{hostport}"

    query = parts.query
    if query:
        pairs = [
            (key, MASK if _SECRET_QUERY_KEYS.search(key) else value)
            for key, value in parse_qsl(query, keep_blank_values=True)
        ]
        query = urlencode(pairs, safe=MASK)

    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def redact_text(text, *secret_urls):
    """Hapus kredensial dari teks bebas (pesan galat, log).

    `secret_urls`: URL asli yang kata sandinya harus disamarkan di mana pun muncul.
    """
    text = _USERINFO_RE.sub(rf"\1:{MASK}@", text or "")
    for url in secret_urls:
        try:
            password = urlsplit(url or "").password
        except ValueError:
            continue
        if password and len(password) >= 3:
            text = text.replace(password, MASK).replace(quote(password, safe=""), MASK)
    return text
