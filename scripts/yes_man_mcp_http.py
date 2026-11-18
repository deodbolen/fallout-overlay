"""Generic MCP Streamable HTTP JSON requests; SSE is not implemented yet."""
import json
import math
import threading
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _invalid_constant(value):
    raise ValueError('Non-JSON numeric constant.')


class StreamableHttpTransport:
    """Send explicit requests to a trusted configured HTTP(S) MCP endpoint.

    No connection is made at construction. Certificates are verified normally;
    redirects are refused rather than forwarding credentials. The timeout is
    the standard-library blocking socket timeout. Responses are capped at 1 MiB.
    """

    def __init__(self, url, bearer_token=None):
        if not isinstance(url, str) or not url.strip():
            raise ValueError('MCP endpoint must be an HTTP or HTTPS URL.')
        url = url.strip()
        try:
            parsed = urlsplit(url)
            if (parsed.scheme not in ('http', 'https') or not parsed.hostname or
                    parsed.username is not None or parsed.password is not None or
                    '#' in url or '\\' in url or
                    any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url) or
                    (parsed.port is not None and not 1 <= parsed.port <= 65535)):
                raise ValueError
        except ValueError:
            raise ValueError('Invalid MCP HTTP or HTTPS endpoint URL.') from None
        if bearer_token is not None and (not isinstance(bearer_token, str) or
                any(ord(char) < 32 or ord(char) > 126 for char in bearer_token)):
            raise ValueError('MCP bearer token must be a printable ASCII string.')
        self._url = url
        self._bearer_token = bearer_token
        self._next_request_id = 1
        self._id_lock = threading.Lock()

    def request(self, method, params=None, timeout=10):
        """POST one JSON-RPC request and return its matching result value."""
        if not isinstance(method, str) or not method.strip():
            raise ValueError('JSON-RPC method must be a nonempty string.')
        if params is not None and not isinstance(params, (dict, list)):
            raise ValueError('JSON-RPC params must be a dictionary or list.')
        try:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
                raise ValueError
            timeout = float(timeout)
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError
        except (ValueError, OverflowError):
            raise ValueError('MCP HTTP timeout must be a positive finite number.') from None
        with self._id_lock:
            identifier = self._next_request_id
            self._next_request_id += 1
        message = {'jsonrpc': '2.0', 'id': identifier, 'method': method}
        if params is not None:
            message['params'] = params
        try:
            body = json.dumps(message, ensure_ascii=False, separators=(',', ':'),
                              allow_nan=False).encode('utf-8')
        except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
            raise ValueError('MCP request could not be serialized as UTF-8 JSON.') from None
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream',
            'MCP-Protocol-Version': '2025-03-26',
        }
        if self._bearer_token:
            headers['Authorization'] = 'Bearer ' + self._bearer_token
        try:
            request = Request(self._url, data=body, headers=headers, method='POST')
            with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
                if response.status != 200:
                    raise RuntimeError('MCP endpoint returned an unsupported HTTP status.')
                content_type = response.headers.get_content_type()
                if content_type == 'text/event-stream':
                    raise RuntimeError('MCP SSE responses are not supported yet.')
                if content_type != 'application/json':
                    raise ValueError('MCP endpoint must return an application/json response.')
                if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                    raise ValueError('Compressed MCP HTTP responses are not supported.')
                limit = 1024 * 1024
                length = response.getheader('Content-Length')
                if length is not None and (not length.isdecimal() or int(length) > limit):
                    raise ValueError('MCP HTTP response exceeds the 1 MiB limit or has an invalid length.')
                raw = response.read(limit + 1)
                if len(raw) > limit:
                    raise ValueError('MCP HTTP response exceeds the 1 MiB limit.')
        except HTTPError as error:
            code = error.code
            error.close()
            if 300 <= code < 400:
                raise RuntimeError('MCP HTTP redirects are not allowed.') from None
            raise RuntimeError('MCP HTTP request failed with status ' + str(code) + '.') from None
        except TimeoutError:
            raise TimeoutError('MCP HTTP request timed out.') from None
        except URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise TimeoutError('MCP HTTP request timed out.') from None
            raise RuntimeError('Could not connect to the configured MCP HTTP endpoint.') from None
        except (OSError, HTTPException):
            raise RuntimeError('MCP HTTP connection failed.') from None
        except (UnicodeError, OverflowError):
            raise ValueError('MCP HTTP request could not be encoded.') from None
        try:
            response = json.loads(raw.decode('utf-8'), parse_constant=_invalid_constant)
        except (UnicodeError, ValueError, RecursionError):
            raise ValueError('MCP HTTP response is not valid UTF-8 JSON.') from None
        if (not isinstance(response, dict) or response.get('jsonrpc') != '2.0' or
                'method' in response or ('result' in response) == ('error' in response)):
            raise ValueError('Malformed MCP JSON-RPC response.')
        if type(response.get('id')) is not int or response['id'] != identifier:
            raise ValueError('MCP JSON-RPC response ID does not match the request.')
        if 'error' in response:
            error = response['error']
            if (not isinstance(error, dict) or type(error.get('code')) is not int or
                    not isinstance(error.get('message'), str)):
                raise ValueError('Malformed MCP JSON-RPC error response.')
            # Never include server error messages/data, which may echo secrets.
            raise RuntimeError('MCP JSON-RPC request failed with error code ' + str(error['code']) + '.')
        return response['result']

    def initialize(self, timeout=10):
        """Negotiate MCP 2025-03-26 and notify only after valid negotiation."""
        protocol_version = '2025-03-26'
        result = self.request('initialize', {
            'protocolVersion': protocol_version,
            'capabilities': {},
            'clientInfo': {'name': 'yes-man-mcp', 'version': '0.1.0'},
        }, timeout=timeout)
        if not isinstance(result, dict):
            raise ValueError('Malformed MCP initialization result.')
        if result.get('protocolVersion') != protocol_version:
            raise ValueError('Unsupported MCP initialization protocol version.')
        if not isinstance(result.get('capabilities'), dict):
            raise ValueError('MCP initialization requires a capabilities object.')
        server_info = result.get('serverInfo')
        if (not isinstance(server_info, dict) or
                any(not isinstance(server_info.get(field), str) or not server_info[field].strip()
                    for field in ('name', 'version'))):
            raise ValueError('MCP initialization requires serverInfo with nonempty name and version strings.')
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream',
            'MCP-Protocol-Version': protocol_version,
        }
        if self._bearer_token:
            headers['Authorization'] = 'Bearer ' + self._bearer_token
        try:
            notification = Request(
                self._url, data=b'{"jsonrpc":"2.0","method":"notifications/initialized"}',
                headers=headers, method='POST')
            with build_opener(_NoRedirect()).open(notification, timeout=timeout) as response:
                if response.status != 202:
                    raise RuntimeError('MCP initialized notification requires HTTP 202 Accepted.')
                # Only an empty body is valid; read at most one byte to detect
                # unexpected content without buffering an unbounded response.
                if response.read(1):
                    raise ValueError('MCP initialized notification response must have an empty body.')
        except HTTPError as error:
            code = error.code
            error.close()
            if 300 <= code < 400:
                raise RuntimeError('MCP HTTP redirects are not allowed.') from None
            raise RuntimeError('MCP initialized notification failed with HTTP status ' + str(code) + '.') from None
        except TimeoutError:
            raise TimeoutError('MCP initialized notification timed out.') from None
        except URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise TimeoutError('MCP initialized notification timed out.') from None
            raise RuntimeError('Could not send the MCP initialized notification.') from None
        except (OSError, HTTPException):
            raise RuntimeError('MCP initialized notification connection failed.') from None
        except (UnicodeError, OverflowError):
            raise ValueError('MCP initialized notification could not be encoded.') from None
        return result
