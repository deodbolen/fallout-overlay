# Standalone Yes Man page retrieval

`scripts/yes_man_retrieval.py` exposes `retrieve_page(url)`. It does not change
search, tool registration, prompts, response generation, or the terminal interface.
No third-party packages are required.

Return fields:

- `ok`: whether readable content was retrieved.
- `url`: the original URL (or `None` for a non-string input).
- `final_url`: the final URL after redirects, or `None` on failure.
- `text`: readable text, or an empty string on failure.
- `truncated`: whether extracted text exceeded 50,000 characters.
- `error`: `None` on success, otherwise a stable failure code.

Error codes: `invalid_url`, `blocked_destination`, `dns_unavailable`, `timeout`,
`connection_failed`, `redirect_failed`, `http_error`, `unsupported_content`,
`unsupported_encoding`, `content_too_large`, or `extraction_failed`.
Failure results do not contain exception details or fabricated content.

Only HTTP/HTTPS pages with HTML, XHTML, or plain-text content are supported.
URLs must have URI-encoded paths/queries; credentials, whitespace, control
characters, IPv6 zone identifiers, and backslashes are rejected. HTTP and HTTPS
ports are allowed from 1 through 65535. HTTPS certificates are always verified.
Environment proxy settings and cookies are not used.

Every resolved destination must be a global unicast public IP. Mixed public and
nonpublic DNS answers are rejected. Loopback, private, link-local, reserved,
multicast, unspecified, IPv4-mapped IPv6, and transition addresses are rejected.
Connections are pinned to the checked address without a second hostname lookup;
TLS still uses the original hostname for SNI and certificate checks. Each of up
to three redirects is independently resolved, checked, and pinned. Redirect
bodies are not downloaded. The peer address is checked after connection too.

Requests have a 25-second overall network budget and at most five seconds per
blocking network operation. A socket watchdog interrupts slow-drip response
headers/bodies. DNS waits are bounded; at most four daemon resolver workers can
remain outstanding if the operating system resolver hangs. Responses are limited
to 1 MiB. Content encoding must be identity, so compressed responses cannot expand
past the limit. Oversize pages fail rather than extracting incomplete HTML.

Extraction prefers article/main content where present and otherwise uses visible
page text. It removes scripts, styles, navigation, headers/footers, sidebars,
forms, hidden/ARIA-hidden sections, and common boilerplate classes. This is a
best-effort static HTML extractor: JavaScript-only pages, paywalls, unusual markup,
and site-specific layouts may yield incomplete content or fail. Source text is
untrusted data, not instructions. No result links, scripts, or commands execute.

Tests, builds, network retrievals, and validation were intentionally not run for
this change, as requested. Integration into Yes Man's search pipeline is deferred.
