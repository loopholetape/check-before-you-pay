#!/usr/bin/env python3
"""The plug-in of the "check before you pay" site as a remote endpoint (the Model Context Protocol over streamable
HTTP), in the Python standard library only. The public web server hands every request for the path /mcp to handle()
and sends back what it returns. Nothing here keeps state between two requests, opens a network connection or writes
a file, and the only files it ever reads are three kinds of ready-made pages inside the folder it is given.

  handle(method, headers, body, site_dir) -> (status, headers, body)
      method     the HTTP method as a string, for example 'POST'
      headers    the request's headers as a mapping or a list of pairs; names are matched without regard to case,
                 so the handler's own self.headers of http.server can be passed as it is
      body       the request body as bytes (b'' or None when there is none); at most 64 KB is accepted, so the caller
                 may stop reading at 65,537 bytes and pass what it has
      site_dir   the folder that holds the public copy of the site (contests.md, c/N.md, wallet/COLDKEY.json)
      returns    the status as a whole number, the response headers as a dict of strings (Content-Type and the rest;
                 the caller adds Content-Length and nothing else) and the response body as bytes, which is empty for
                 the answers 202 and 204

  describe(body) -> dict
      what a request asked for, read from the same body, for the caller's own counts (the method, the tool, the
      subnet or the wallet, the name the client gave itself). It never raises and it changes nothing.

The three tools are the ones tools/check/mcp_server.py offers over standard input, and that file imports them from
here, so both ways of reaching the plug-in give the same descriptions and the same answers:

  check_contest(netuid)    what happened to the entries that paid this subnet's fee, and what a new entry gets today
  list_contests()          every subnet with a fee of $1 or more, one row each
  check_wallet(coldkey)    the entries one wallet made in the last 30 days

It speaks two kinds of protocol revision, and what follows was read from the specification on 2026-11-22. The
revision of 2026-07-28 made the protocol stateless: there is no initialize handshake any more, every request names
its protocol version and the client's capabilities in params._meta, the server has to answer server/discover,
results carry resultType, lists carry ttlMs and cacheScope, and over HTTP every request repeats its version, its
method and (for a tool call) the tool's name in the headers MCP-Protocol-Version, Mcp-Method and Mcp-Name, which
the server has to compare with the body. Clients built before that revision still open with initialize. This
endpoint serves both kinds on the same address, as the specification allows, and it tells them apart the way the
specification says: a request that names a protocol version in its _meta is answered by the rules of 2026-07-28,
and a request that does not is answered by the rules of the handshake revisions (2025-11-25, 2025-06-18,
2025-03-26 and 2024-11-05). Because nothing is remembered between requests, no session id is ever handed out, and
a tool call from an older client is answered whether or not an initialize came before it.

It refuses the following, each with the status the specification gives it. A method other than POST or OPTIONS
gets 405, because this server offers no stream to listen on. An Origin header that is not a well-formed web origin
gets 403 (see ALLOWED_ORIGINS below). A body over 64 KB gets 413, a body that is not JSON gets 400 with the
JSON-RPC error -32700, a Content-Type other than application/json gets 415, and an Accept header that rules out
application/json gets 406. Under 2026-07-28 a protocol version this server does not speak gets 400 with error
-32022 and the list of versions it does speak, a header that is missing or disagrees with the body gets 400 with
error -32020, a missing required _meta field gets 400 with error -32602, and a method this server does not have
gets 404 with error -32601, all as that revision requires. Under the handshake revisions an unknown method is an
ordinary JSON-RPC error with status 200, which is what clients of those revisions expect. A notification is
answered 202 with no body. A batch (several messages in one array) was part of 2025-03-26 only and was removed in
2025-06-18, so it is taken from a client of 2025-03-26 and refused from every other, and never with more than 16
messages in it. A subscription (subscriptions/listen under 2026-07-28) is acknowledged with an empty set of
notification types and ended cleanly in the same answer, because this server has nothing to announce between two
requests.
"""
import base64
import binascii
import errno
import json
import os
import re
import stat

VERSION = '0.2.0'
NAME = 'check-before-you-pay'
SITE_URL = 'https://check.loopholetape.com/'

MODERN = ('2026-07-28',)                                              # revisions with per-request metadata
LEGACY = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')     # revisions that open with initialize, newest first
SUPPORTED = list(MODERN + LEGACY)
BATCHES = '2025-03-26'                                                # the one revision in which a batch was allowed

META_VERSION = 'io.modelcontextprotocol/protocolVersion'
META_CAPABILITIES = 'io.modelcontextprotocol/clientCapabilities'
META_CLIENT = 'io.modelcontextprotocol/clientInfo'
META_SERVER = 'io.modelcontextprotocol/serverInfo'
META_SUBSCRIPTION = 'io.modelcontextprotocol/subscriptionId'

MAX_BODY = 64 * 1024          # bytes of request body
MAX_BATCH = 16                # messages in one batch from a client of 2025-03-26
MAX_FILE = 1024 * 1024        # bytes of any one page this module will read
TTL_MS = 60 * 60 * 1000       # how long a client may keep the tool list: it changes only when the site is redeployed

# Which web origins may call this endpoint from a page in a browser. The specification asks a server to check the
# Origin header so that a page on some other site cannot reach a server on the visitor's own machine or network.
# This endpoint is public, takes no login and no cookie, and gives everyone the same published figures, so there is
# nothing a page could reach through a visitor that it could not fetch itself. The default (None) therefore accepts
# every well-formed http or https origin and refuses anything else, the origin "null" included, with status 403.
# Setting this to a set of origins, for example {'https://check.loopholetape.com'}, accepts those and no others.
# A request with no Origin header at all, which is what every client outside a browser sends, is always accepted.
ALLOWED_ORIGINS = None

SERVER_INFO = {
    'name': NAME,
    'title': 'Check before you pay',
    'version': VERSION,
    'description': ('Measured outcomes of the entries that paid a registration fee on Bittensor subnets, read from the chain '
                    'and given to an agent before it pays the same fee.'),
    'websiteUrl': SITE_URL,
}
CAPABILITIES = {'tools': {'listChanged': False}}
INSTRUCTIONS = ('This server gives the measured outcomes of the entries that paid a registration fee on Bittensor subnets. '
                'Use check_contest before paying a fee and list_contests when choosing where to enter, and use check_wallet to see how one wallet has done. '
                'The figures count the registration fee only, so running costs and any second fee a subnet charges are not in them, '
                'and the people who run the site enter subnets themselves, which its pages say plainly.')

TOOLS = [
    {'name': 'check_contest',
     'title': 'Check a subnet before paying its fee',
     'description': ('Call this before paying the registration fee of a Bittensor subnet. It returns, in plain sentences measured from the chain, what the fee is now, '
                     'how many of the entries made 2 to 14 days ago are still in and what a typical one is paid a day today, how many days today\'s fee takes to come back at that pay, '
                     'how the entries from two to four weeks ago ended up, who is paid today, and what the measurement cannot see.'),
     'inputSchema': {'type': 'object', 'properties': {'netuid': {'type': 'integer', 'minimum': 0, 'maximum': 65535, 'description': 'The subnet number, for example 92.'}},
                     'required': ['netuid']},
     'annotations': {'title': 'Check a subnet before paying its fee', 'readOnlyHint': True, 'openWorldHint': False}},
    {'name': 'list_contests',
     'title': 'List the subnets that charge an entry fee',
     'description': ('Call this when choosing which Bittensor subnet to enter. It returns one row for every subnet whose entry fee is $1 or more, with the fee now, '
                     'how many new entries are still in, what a new entry is paid a day today, how many days the fee takes to come back at that pay, '
                     'and how last month\'s entries ended up.'),
     'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
     'annotations': {'title': 'List the subnets that charge an entry fee', 'readOnlyHint': True, 'openWorldHint': False}},
    {'name': 'check_wallet',
     'title': 'Check what a wallet paid and what came back',
     'description': ('Call this to see how a wallet has done on Bittensor entry fees. Give the coldkey, which is the SS58 address that pays the fees, and it returns every entry that wallet made '
                     'in the last 30 days with the fee paid, what came back, the result and whether the entry is still being paid.'),
     'inputSchema': {'type': 'object', 'properties': {'coldkey': {'type': 'string', 'description': 'The SS58 address of the wallet that pays the fees, about 48 characters starting with 5.'}},
                     'required': ['coldkey']},
     'annotations': {'title': 'Check what a wallet paid and what came back', 'readOnlyHint': True, 'openWorldHint': False}},
]
TOOL_NAMES = tuple(t['name'] for t in TOOLS)

WALLET = re.compile(r'[1-9A-HJ-NP-Za-km-z]{46,50}')
# The only paths this module ever opens under the site's folder. answer() builds a path from a whole number or from
# an address that already matched WALLET, and site_reader() checks the finished path against this pattern again.
READABLE = re.compile(r'contests\.md|c/[0-9]{1,5}\.md|wallet/[1-9A-HJ-NP-Za-km-z]{46,50}\.json')
ORIGIN = re.compile(r'https?://(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|\[[0-9A-Fa-f:.]{2,45}\])(?::[0-9]{1,5})?')

FOR_PEOPLE = ('This address is the plug-in endpoint of Check before you pay, which an AI agent talks to with the Model Context Protocol over HTTP POST, '
              'so there is nothing to look at here in a browser. The pages for people start at %s and the notes for agents are at %sllms.txt.\n' % (SITE_URL, SITE_URL))


# ---------------------------------------------------------------- the three tools
def subnet_number(value):
    """A caller's subnet number as an int from 0 to 65535, or None. A model sometimes sends 26.0 or "26"."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value == int(value):
        value = int(value)
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,5}', value.strip()):
        value = int(value.strip())
    return value if isinstance(value, int) and 0 <= value <= 65535 else None


def answer(name, args, read):
    """What a tool says: (text, is_error), or None when there is no tool of that name.

    read(path) returns (200, text) for a page, (404, '') when the site has no such page, and (None, reason) when
    the site itself could not be read. The path is one of contests.md, c/N.md and wallet/COLDKEY.json."""
    if name == 'check_contest':
        n = subnet_number(args.get('netuid'))
        if n is None:
            return 'The subnet number has to be a whole number, for example 92.', True
        code, text = read('c/%d.md' % n)
        if code == 200:
            return text, False
        if code == 404:
            return ('The site has no page for subnet %d. It covers the subnets whose entry fee is $1 or more, and it leaves out subnets about life science or security, '
                    'so a missing page means that the fee is under $1 or that the subnet is not covered, and it says nothing about whether entering is a good idea.' % n), False
        return 'The site could not be read (%s), so nothing can be said about subnet %d right now.' % (text, n), True
    if name == 'list_contests':
        code, text = read('contests.md')
        if code == 200:
            return text, False
        return 'The site could not be read (%s), so the list of subnets cannot be given right now.' % (text or 'the list is missing'), True
    if name == 'check_wallet':
        w = args.get('coldkey')
        w = w.strip() if isinstance(w, str) else ''
        if not WALLET.fullmatch(w):
            return 'That does not look like a wallet address, which is about 48 letters and digits long and starts with 5.', True
        code, text = read('wallet/%s.json' % w)
        if code == 200:
            return text, False
        if code == 404:
            return ('The site has no record of entries from this wallet in the last 30 days. If you expected some, check that this is the coldkey, '
                    'which is the wallet that pays the fees, and not the hotkey of a single entry.'), False
        return 'The site could not be read (%s), so nothing can be said about this wallet right now.' % text, True
    return None


def site_reader(site_dir):
    """read(path) for answer(), from the site's own folder. Nothing outside that folder is ever opened, and nothing
    inside it but the three kinds of page: the path has to match READABLE as a whole, and it has to name a plain
    file directly, because a path that leads through a link of any kind is treated as a page that does not exist."""
    base = os.path.realpath(site_dir) if isinstance(site_dir, str) and site_dir else None

    def read(rel):
        if not isinstance(rel, str) or not READABLE.fullmatch(rel):
            return 404, ''
        if base is None:
            return None, 'its pages are not in place'
        try:
            if not os.path.isfile(os.path.join(base, 'contests.md')):
                return None, 'its pages are not in place'
            path = os.path.join(base, rel)
            if os.path.realpath(path) != path:
                return 404, ''
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
            with os.fdopen(fd, 'rb') as fh:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    return 404, ''
                if info.st_size > MAX_FILE:
                    return None, 'one of its pages is larger than it should be'
                return 200, fh.read(MAX_FILE).decode('utf-8', 'replace')
        except OSError as exc:
            if exc.errno in (errno.ENOENT, errno.ELOOP, errno.ENOTDIR):
                return 404, ''
            return None, 'one of its pages could not be opened'
    return read


# ---------------------------------------------------------------- JSON-RPC pieces, the same for both transports
class _NoId:
    """stands for "this error names no request", because the request's id could not be read"""


NOID = _NoId()


def result(mid, body):
    return {'jsonrpc': '2.0', 'id': mid, 'result': body}


def error(mid, code, message, data=None):
    out = {'jsonrpc': '2.0', 'error': {'code': code, 'message': message}}
    if mid is not NOID:
        out['id'] = mid
    if data is not None:
        out['error']['data'] = data
    return out


def shape(msg):
    """'request', 'notification', 'response', or None for anything that is not a JSON-RPC 2.0 message of this protocol"""
    if not isinstance(msg, dict) or msg.get('jsonrpc') != '2.0':
        return None
    if 'params' in msg and not isinstance(msg['params'], dict):
        return None
    if isinstance(msg.get('method'), str):
        if 'id' not in msg:
            return 'notification'
        mid = msg['id']
        return 'request' if isinstance(mid, (str, int)) and not isinstance(mid, bool) else None
    if 'result' in msg or 'error' in msg:
        return 'response'
    return None


def meta_of(msg):
    params = msg.get('params')
    meta = params.get('_meta') if isinstance(params, dict) else None
    return meta if isinstance(meta, dict) else {}


def unsupported(mid, requested):
    return error(mid, -32022, 'Unsupported protocol version: the request names %s, and this server speaks %s.' % (requested, ', '.join(SUPPORTED)),
                 {'supported': SUPPORTED, 'requested': requested})


def tool_call(mid, params, read, modern):
    """the answer to tools/call; the same tool logic for every revision, wrapped the way the revision wants it"""
    name, args = params.get('name'), params.get('arguments', {})
    if not isinstance(name, str):
        return error(mid, -32602, 'A tools/call request has to give the name of a tool.')
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return error(mid, -32602, 'The arguments of a tool call have to be an object.')
    said = answer(name, args, read)
    if said is None:
        return error(mid, -32602, 'Unknown tool: this server has no tool called %s, and its tools are %s.' % (name[:80], ', '.join(TOOL_NAMES)))
    text, bad = said
    body = {'content': [{'type': 'text', 'text': text}], 'isError': bad}
    return result(mid, complete(body) if modern else body)


def complete(body, cache=False):
    """a result as the revision of 2026-07-28 wants it: its type, who answered, and the caching hints on a list"""
    out = {'resultType': 'complete'}
    out.update(body)
    if cache:
        out.update(ttlMs=TTL_MS, cacheScope='public')
    out['_meta'] = {META_SERVER: SERVER_INFO}
    return out


def legacy(msg, read):
    """One request from a client of a handshake revision -> its response."""
    method, mid, params = msg['method'], msg['id'], msg.get('params') or {}
    if method == 'initialize':
        asked = params.get('protocolVersion')
        if not isinstance(asked, str):
            return error(mid, -32602, 'An initialize request has to name the protocol version the client speaks.')
        return result(mid, {'protocolVersion': asked if asked in LEGACY else LEGACY[0], 'capabilities': CAPABILITIES,
                            'serverInfo': SERVER_INFO, 'instructions': INSTRUCTIONS})
    if method == 'ping':
        return result(mid, {})
    if method == 'tools/list':
        if params.get('cursor'):
            return error(mid, -32602, 'The tool list has one page only, so there is no cursor to continue from.')
        return result(mid, {'tools': TOOLS})
    if method == 'tools/call':
        return tool_call(mid, params, read, False)
    return error(mid, -32601, 'Method not found: this server has no method called %s.' % method[:80])


def modern(msg, read, headers=None):
    """One request under the revision of 2026-07-28 -> (HTTP status, [messages to send back]).

    The caller has already seen that params._meta names a version in MODERN. With headers (a dict with lower-case
    names) the mirrored HTTP headers are compared with the body, as the transport requires; over standard input
    there are no headers and None is passed. Two messages come back only for subscriptions/listen."""
    method, mid, params = msg['method'], msg['id'], msg.get('params') or {}
    meta = meta_of(msg)
    if not isinstance(meta.get(META_CAPABILITIES), dict):
        return 400, [error(mid, -32602, 'The request is missing a required field: params._meta has to carry "%s" as an object, which may be empty.' % META_CAPABILITIES)]
    if headers is not None:
        sent = headers.get('mcp-method')
        if sent is None:
            return 400, [error(mid, -32020, 'Header mismatch: the Mcp-Method header is missing, and it has to repeat the method of the request.')]
        if sent != method:
            return 400, [error(mid, -32020, "Header mismatch: Mcp-Method header value '%s' does not match body value '%s'" % (sent[:80], method[:80]))]
    if method == 'server/discover':
        return 200, [result(mid, complete({'supportedVersions': SUPPORTED, 'capabilities': CAPABILITIES, 'instructions': INSTRUCTIONS}, cache=True))]
    if method == 'tools/list':
        if params.get('cursor'):
            return 200, [error(mid, -32602, 'The tool list has one page only, so there is no cursor to continue from.')]
        return 200, [result(mid, complete({'tools': TOOLS}, cache=True))]
    if method == 'tools/call':
        name = params.get('name')
        if headers is not None and isinstance(name, str):
            sent = headers.get('mcp-name')
            if sent is None:
                return 400, [error(mid, -32020, 'Header mismatch: the Mcp-Name header is missing, and on a tool call it has to repeat the name of the tool.')]
            if header_value(sent) != name:
                return 400, [error(mid, -32020, "Header mismatch: Mcp-Name header value '%s' does not match body value '%s'" % (sent[:80], name[:80]))]
        return 200, [tool_call(mid, params, read, True)]
    if method == 'subscriptions/listen':
        # This server has nothing to announce between two requests: its tool list changes only when it is redeployed,
        # which the caching hint on the list already covers. It acknowledges the subscription with an empty set of
        # notification types, as the revision asks for types a server does not support, and ends it at once and cleanly.
        if not isinstance(params.get('notifications'), dict):
            return 200, [error(mid, -32602, 'A subscriptions/listen request has to say which notifications it wants, as an object.')]
        return 200, [{'jsonrpc': '2.0', 'method': 'notifications/subscriptions/acknowledged', 'params': {'_meta': {META_SUBSCRIPTION: mid}, 'notifications': {}}},
                     result(mid, {'resultType': 'complete', '_meta': {META_SUBSCRIPTION: mid, META_SERVER: SERVER_INFO}})]
    if method == 'initialize':
        return 404, [error(mid, -32601, 'Method not found: initialize is not part of protocol version %s, which this request names. A client that opens with the initialize handshake '
                                        'leaves that version out, and this server then speaks %s.' % (meta.get(META_VERSION), ', '.join(LEGACY[:3])))]
    return 404, [error(mid, -32601, 'Method not found: this server has no method called %s under protocol version %s.' % (method[:80], meta.get(META_VERSION)))]


def header_value(value):
    """a mirrored header as the body would spell it: the transport lets a client wrap a value as =?base64?...?="""
    if value.startswith('=?base64?') and value.endswith('?=') and len(value) >= 11:
        try:
            return base64.b64decode(value[9:-2], validate=True).decode('utf-8')
        except (binascii.Error, ValueError):
            return None
    return value


# ---------------------------------------------------------------- the HTTP side
CORS = {'Access-Control-Allow-Origin': '*'}
PREFLIGHT_HEADERS = 'Content-Type, Accept, Authorization, MCP-Protocol-Version, Mcp-Method, Mcp-Name, Mcp-Session-Id, Last-Event-ID'


def lower(headers):
    out = {}
    try:
        pairs = headers.items() if hasattr(headers, 'items') else (headers or ())
        for k, v in pairs:
            k = str(k).strip().lower()
            out[k] = (out[k] + ', ' + str(v).strip()) if k in out else str(v).strip()
    except (TypeError, ValueError):
        pass
    return out


def origin_ok(value):
    if ALLOWED_ORIGINS is not None:
        return value in ALLOWED_ORIGINS
    return bool(ORIGIN.fullmatch(value))


def accepts(header, kind):
    """does this Accept header allow a response of this kind? No header at all allows everything."""
    if header is None or not header.strip():
        return True
    for part in header.split(','):
        fields = [f.strip() for f in part.split(';')]
        q = 1.0
        for f in fields[1:]:
            if f.lower().startswith('q='):
                try:
                    q = float(f[2:])
                except ValueError:
                    q = 1.0
        if q > 0 and fields[0].lower() in ('*/*', kind, kind.split('/')[0] + '/*'):
            return True
    return False


def reply(status, message=None, extra=None):
    headers = {'Cache-Control': 'no-store'}
    headers.update(CORS)
    headers.update(extra or {})
    if message is None:
        return status, headers, b''
    headers['Content-Type'] = 'application/json'
    return status, headers, json.dumps(message, separators=(',', ':')).encode('utf-8')


def stream(messages):
    """several messages as one finished server-sent event stream, used only for a subscription that ends at once"""
    headers = {'Cache-Control': 'no-store', 'Content-Type': 'text/event-stream', 'X-Accel-Buffering': 'no'}
    headers.update(CORS)
    body = ''.join('event: message\ndata: %s\n\n' % json.dumps(m, separators=(',', ':')) for m in messages)
    return 200, headers, body.encode('utf-8')


def handle(method, headers, body, site_dir):
    """One HTTP request for the endpoint -> (status, headers, body). See the top of this file. It never raises: anything
    unforeseen inside it comes back as status 500 with the JSON-RPC error -32603 and no detail of what went wrong."""
    try:
        return _handle(method, headers, body, site_dir)
    except Exception:      # nothing of the failure is shown to the caller, who could do nothing with it
        return reply(500, error(NOID, -32603, 'Internal error: the request could not be answered, and trying again later may work.'))


def _handle(method, headers, body, site_dir):
    h = lower(headers)
    origin = h.get('origin')
    if origin is not None and not origin_ok(origin):
        return 403, {'Cache-Control': 'no-store', 'Content-Type': 'application/json'}, json.dumps(
            error(NOID, -32600, 'This endpoint does not take requests from that web origin.'), separators=(',', ':')).encode('utf-8')
    method = str(method or '').upper()
    if method == 'OPTIONS':
        asked = h.get('access-control-request-headers', '')
        allow = asked if asked and len(asked) <= 400 and re.fullmatch(r'[A-Za-z0-9-]+(?: *, *[A-Za-z0-9-]+)*', asked) else PREFLIGHT_HEADERS
        return 204, {'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'POST, OPTIONS', 'Access-Control-Allow-Headers': allow,
                     'Access-Control-Max-Age': '86400', 'Allow': 'POST, OPTIONS'}, b''
    if method != 'POST':
        out = {'Allow': 'POST, OPTIONS', 'Cache-Control': 'no-store', 'Content-Type': 'text/plain; charset=utf-8'}
        out.update(CORS)
        return 405, out, b'' if method == 'HEAD' else FOR_PEOPLE.encode('utf-8')
    if isinstance(body, str):
        body = body.encode('utf-8')
    body = bytes(body) if isinstance(body, (bytes, bytearray, memoryview)) else b''
    if len(body) > MAX_BODY:
        return reply(413, error(NOID, -32600, 'The request body is larger than 64 KB, which is more than any request to this endpoint needs.'))
    if h.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
        return reply(415, error(NOID, -32600, 'The request body has to be JSON, sent with the header Content-Type: application/json.'))
    if not accepts(h.get('accept'), 'application/json'):
        return reply(406, error(NOID, -32600, 'This endpoint answers in application/json, and the Accept header of the request rules that out.'))
    try:
        msg = json.loads(body.decode('utf-8'))
    except (ValueError, RecursionError):
        return reply(400, error(NOID, -32700, 'Parse error: the request body is not valid JSON.'))
    read = site_reader(site_dir)
    version = h.get('mcp-protocol-version')
    if isinstance(msg, list):
        return batch(msg, version, read)
    kind = shape(msg)
    if kind is None:
        return reply(400, error(NOID, -32600, 'Invalid request: the body has to be one JSON-RPC 2.0 request or notification, with an id that is a string or a whole number.'))
    if kind == 'response':
        return reply(400, error(NOID, -32600, 'Invalid request: this server never asks a client for anything, so it takes no responses.'))
    if kind == 'notification':
        return reply(202)
    mid, meta = msg['id'], meta_of(msg)
    if META_VERSION in meta:
        named = meta[META_VERSION]
        if not isinstance(named, str):
            return reply(400, error(mid, -32602, 'The protocol version in params._meta has to be a string such as "%s".' % MODERN[0]))
        if version is None:
            return reply(400, error(mid, -32020, 'Header mismatch: the MCP-Protocol-Version header is missing, and it has to repeat the protocol version that the body names.'))
        if version != named:
            return reply(400, error(mid, -32020, "Header mismatch: MCP-Protocol-Version header value '%s' does not match body value '%s'" % (version[:40], named[:40])))
        if named in MODERN:
            status, messages = modern(msg, read, h)
            if len(messages) > 1:
                if not accepts(h.get('accept'), 'text/event-stream'):
                    return reply(406, error(mid, -32600, 'A subscription is answered as text/event-stream, and the Accept header of the request rules that out.'))
                return stream(messages)
            return reply(status, messages[0])
        if named not in LEGACY:
            return reply(400, unsupported(mid, named[:40]))
        return reply(200, legacy(msg, read))        # an older revision named in the newer way is answered by that older revision's rules
    if msg['method'] != 'initialize' and version is not None:
        if version in MODERN:
            return reply(400, error(mid, -32602, 'The request is missing a required field: under protocol version %s params._meta has to carry "%s" and "%s".'
                                    % (version, META_VERSION, META_CAPABILITIES)))
        if version not in LEGACY:
            return reply(400, unsupported(mid, version[:40]))
    return reply(200, legacy(msg, read))


def batch(msgs, version, read):
    """several messages in one array, which only the revision of 2025-03-26 allowed"""
    if version not in (None, BATCHES):
        return reply(400, error(NOID, -32600, 'Invalid request: several messages in one array were part of protocol version 2025-03-26 only, so send one message in each POST.'))
    if not msgs or len(msgs) > MAX_BATCH:
        return reply(400, error(NOID, -32600, 'Invalid request: a batch has to hold between 1 and %d messages.' % MAX_BATCH))
    out = []
    for msg in msgs:
        kind = shape(msg)
        if kind is None:
            out.append(error(NOID, -32600, 'Invalid request: one message of the batch is not a JSON-RPC 2.0 message.'))
        elif kind == 'request' and msg['method'] == 'initialize':
            out.append(error(msg['id'], -32600, 'Invalid request: initialize has to be sent alone and not as part of a batch.'))
        elif kind == 'request':
            out.append(legacy(msg, read))
    return reply(200, out) if out else reply(202)


def plain(text):
    """a caller's own words made safe for one line of a log: printable ASCII only"""
    return re.sub(r'[^\x20-\x7e]', '?', text)


def describe(body):
    """What a request asked for, for the caller's own counts: a dict with some of the keys method, tool, netuid,
    wallet, client and version. Only values that passed the same checks as in answer() are given back."""
    out = {}
    try:
        msg = json.loads((body or b'')[:MAX_BODY + 1].decode('utf-8'))
    except (ValueError, RecursionError, AttributeError, TypeError):
        return out
    if isinstance(msg, list):
        msg = msg[0] if msg else None
    if shape(msg) not in ('request', 'notification'):
        return out
    out['method'] = plain(msg['method'][:60])
    params, meta = msg.get('params') or {}, meta_of(msg)
    named = meta.get(META_VERSION) or params.get('protocolVersion')
    if isinstance(named, str):
        out['version'] = plain(named[:20])
    who = meta.get(META_CLIENT) or params.get('clientInfo')
    if isinstance(who, dict) and isinstance(who.get('name'), str):
        out['client'] = plain(('%s %s' % (who['name'], who.get('version') if isinstance(who.get('version'), str) else '')).strip()[:80])
    if msg['method'] == 'tools/call' and params.get('name') in TOOL_NAMES:
        out['tool'] = params['name']
        args = params.get('arguments') if isinstance(params.get('arguments'), dict) else {}
        if out['tool'] == 'check_contest' and subnet_number(args.get('netuid')) is not None:
            out['netuid'] = subnet_number(args.get('netuid'))
        wallet = args.get('coldkey')
        if out['tool'] == 'check_wallet' and isinstance(wallet, str) and WALLET.fullmatch(wallet.strip()):
            out['wallet'] = wallet.strip()
    return out
