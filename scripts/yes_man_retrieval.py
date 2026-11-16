"""Reusable public-page retrieval, also used by Yes Man's search evidence adapter.

No proxies, cookies, browser execution, or third-party dependencies. DNS answers
are checked and the connection is pinned to a checked address, including for each
redirect. Returned page text is untrusted source material, never instructions.
"""
import http.client
from html.parser import HTMLParser
import ipaddress
import queue
import re
import socket
import ssl
import threading
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

_MAX_BYTES = 1024 * 1024
_MAX_TEXT = 50000
_TOTAL_SECONDS = 25
_DNS_SLOTS = threading.BoundedSemaphore(4)
_REDIRECTS = {301, 302, 303, 307, 308}
_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
_SKIP = {'head', 'script', 'style', 'nav', 'header', 'footer', 'aside', 'form', 'button', 'select',
         'textarea', 'svg', 'canvas', 'iframe', 'noscript', 'template', 'menu', 'dialog'}
_BLOCK = {'p', 'div', 'article', 'main', 'section', 'li', 'ul', 'ol', 'h1', 'h2', 'h3',
          'h4', 'h5', 'h6', 'blockquote', 'pre', 'tr', 'br', 'hr'}
_BOILERPLATE = {'navigation', 'navbar', 'sidebar', 'advertisement', 'ads', 'cookie-banner',
                'cookie-consent', 'social-share', 'related-posts', 'site-footer', 'site-header'}


class _Failure(Exception):
    pass


def _remaining(deadline):
    left = deadline - time.monotonic()
    if left <= 0:
        raise _Failure('timeout')
    return min(5, left)


def _public(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if (not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified or
            ip.is_loopback or ip.is_link_local or ip.is_private):
        return False
    if isinstance(ip, ipaddress.IPv6Address) and (ip.ipv4_mapped or ip.sixtofour or ip.teredo):
        return False
    return True


def _url(value):
    if (not isinstance(value, str) or not value or len(value) > 4096 or
            any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value) or '\\' in value):
        raise _Failure('invalid_url')
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        if (parsed.scheme not in ('http', 'https') or not host or parsed.username is not None or
                parsed.password is not None or '%' in host or not 1 <= port <= 65535):
            raise ValueError
        host = host.encode('idna').decode('ascii').lower().rstrip('.')
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal', '.onion')):
            raise _Failure('blocked_destination')
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not _public(host):
                raise _Failure('blocked_destination')
        target = urlunsplit(('', '', parsed.path or '/', parsed.query, ''))
        # URLs must be URI-encoded; do not silently rewrite user-supplied paths.
        target.encode('ascii')
        return parsed, host, port, target
    except (ValueError, UnicodeError):
        raise _Failure('invalid_url') from None


def _addresses(host, port, deadline):
    # Resolver calls have no portable per-call timeout. Bound outstanding workers
    # and wait time; a stuck OS resolver cannot hang this caller indefinitely.
    if not _DNS_SLOTS.acquire(blocking=False):
        raise _Failure('dns_unavailable')
    result = queue.Queue(maxsize=1)
    def resolve():
        try:
            result.put(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
        except OSError:
            result.put(None)
        finally:
            _DNS_SLOTS.release()
    try:
        threading.Thread(target=resolve, daemon=True).start()
    except RuntimeError:
        _DNS_SLOTS.release()
        raise _Failure('dns_unavailable') from None
    try:
        answers = result.get(timeout=_remaining(deadline))
    except queue.Empty:
        raise _Failure('timeout') from None
    if not answers:
        raise _Failure('dns_unavailable')
    if any(not _public(answer[4][0]) for answer in answers):
        raise _Failure('blocked_destination')
    return answers[:8]


def _connect(host, port, secure, deadline):
    for family, kind, protocol, _, address in _addresses(host, port, deadline):
        connection = None
        sock = socket.socket(family, kind, protocol)
        try:
            sock.settimeout(_remaining(deadline))
            sock.connect(address)
            if not _public(sock.getpeername()[0]):
                raise _Failure('blocked_destination')
            if secure:
                sock.settimeout(_remaining(deadline))
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            # Attach the pinned socket: http.client must never resolve host again.
            connection = http.client.HTTPConnection(host, port, timeout=_remaining(deadline))
            connection.sock = sock
            return connection
        except (OSError, ssl.SSLError):
            sock.close()
            if connection is not None:
                connection.close()
        except BaseException:
            sock.close()
            raise
    raise _Failure('connection_failed')


class _Readable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.all = []
        self.article = []

    def _add(self, text):
        if not self.stack or not self.stack[-1][1]:
            self.all.append(text)
            if self.stack and self.stack[-1][2]:
                self.article.append(text)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        parent_skip = bool(self.stack and self.stack[-1][1])
        parent_article = bool(self.stack and self.stack[-1][2])
        labels = set(((attributes.get('class') or '') + ' ' + (attributes.get('id') or '')).lower().split())
        role = (attributes.get('role') or '').lower()
        skip = (parent_skip or tag in _SKIP or 'hidden' in attributes or
                attributes.get('aria-hidden') == 'true' or bool(labels & _BOILERPLATE) or
                role in {'navigation', 'banner', 'contentinfo', 'complementary'})
        if tag in _BLOCK and not skip:
            self._add('\n')
        if tag not in _VOID:
            if len(self.stack) >= 256:
                raise _Failure('extraction_failed')
            self.stack.append((tag, skip, parent_article or tag in {'article', 'main'} or role == 'main'))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in _BLOCK:
            self._add('\n')
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self._add(data)

    def text(self):
        article = ''.join(self.article)
        return article if article.strip() else ''.join(self.all)


def _extract(raw, content_type, charset):
    try:
        decoded = raw.decode(charset or 'utf-8', errors='replace')
    except LookupError:
        decoded = raw.decode('utf-8', errors='replace')
    if content_type != 'text/plain':
        parser = _Readable()
        parser.feed(decoded)
        parser.close()
        decoded = parser.text()
    lines = [re.sub(r'[^\S\n]+', ' ', line).strip() for line in decoded.splitlines()]
    text = '\n'.join(line for line in lines if line)
    text = ''.join(char for char in text if char.isprintable() or char == '\n')
    if not text:
        raise _Failure('extraction_failed')
    return text[:_MAX_TEXT], len(text) > _MAX_TEXT


def _interrupt(sock):
    # shutdown wakes buffered HTTP reads too, including slow-drip headers/bodies.
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def retrieve_page(url):
    """Fetch one public page, returning a bounded, JSON-compatible result.

    Success: {ok: True, url: original URL, final_url: final URL, text: extracted
    text, truncated: bool, error: None}. Failure has ok=False, text='',
    truncated=False, final_url=None and a stable error code. Redirects (up to 3)
    are revalidated and DNS-pinned; HTTPS certificate verification is mandatory.
    Supports HTML/XHTML and plain text only. No page scripts or result URLs run.
    """
    result = {'ok': False, 'url': url if isinstance(url, str) else None,
              'final_url': None, 'text': '', 'truncated': False, 'error': None}
    deadline = time.monotonic() + _TOTAL_SECONDS
    current = url
    try:
        for hop in range(4):
            parsed, host, port, target = _url(current)
            connection = _connect(host, port, parsed.scheme == 'https', deadline)
            transport = connection.sock
            response = None
            watchdog = threading.Timer(max(.001, deadline - time.monotonic()), _interrupt, args=(transport,))
            watchdog.daemon = True
            watchdog.start()
            try:
                connection.sock.settimeout(_remaining(deadline))
                connection.request('GET', target, headers={
                    'User-Agent': 'Fallout-YesMan/1.0',
                    'Accept': 'text/html, application/xhtml+xml, text/plain',
                    'Accept-Encoding': 'identity', 'Connection': 'close'})
                connection.sock.settimeout(_remaining(deadline))
                response = connection.getresponse()
                if response.status in _REDIRECTS:
                    location = response.getheader('Location')
                    if not location or hop == 3:
                        raise _Failure('redirect_failed')
                    current = urljoin(current, location)
                    continue
                if not 200 <= response.status < 300:
                    raise _Failure('http_error')
                content_type = response.headers.get_content_type()
                if content_type not in {'text/html', 'application/xhtml+xml', 'text/plain'}:
                    raise _Failure('unsupported_content')
                if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                    raise _Failure('unsupported_encoding')
                length = response.getheader('Content-Length')
                if length is not None and (not length.isdecimal() or int(length) > _MAX_BYTES):
                    raise _Failure('content_too_large')
                raw = bytearray()
                while len(raw) <= _MAX_BYTES:
                    _remaining(deadline)
                    transport.settimeout(_remaining(deadline))
                    chunk = response.read1(min(16384, _MAX_BYTES + 1 - len(raw)))
                    if not chunk:
                        break
                    raw.extend(chunk)
                if len(raw) > _MAX_BYTES:
                    raise _Failure('content_too_large')
                text, truncated = _extract(bytes(raw), content_type, response.headers.get_content_charset())
                result.update(ok=True, final_url=current, text=text, truncated=truncated)
                return result
            finally:
                watchdog.cancel()
                if response is not None:
                    response.close()
                connection.close()
        raise _Failure('redirect_failed')
    except _Failure as error:
        result['error'] = str(error)
    except (TimeoutError, socket.timeout):
        result['error'] = 'timeout'
    except (OSError, http.client.HTTPException):
        result['error'] = 'timeout' if time.monotonic() >= deadline else 'connection_failed'
    except (ValueError, UnicodeError, RecursionError):
        result['error'] = 'extraction_failed'
    return result
