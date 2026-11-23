#!/usr/bin/env python3
"""A plug-in that hands the "check before you pay" site to an AI agent as three tools (the Model Context Protocol,
over standard input and output, no dependency beyond Python). It only reads the site's own plain-text and data
files over the network, so it shows an agent exactly what the site shows anyone.

  check_contest(netuid)    what happened to the entries that paid this subnet's fee, and what a new entry gets today
  list_contests()          every subnet with a fee of $1 or more, one row each
  check_wallet(coldkey)    the entries one wallet made in the last 30 days

Most operators do not need this file, because the same three tools answer at https://check.loopholetape.com/mcp
and are added with one line, for example in Claude Code:
  claude mcp add --transport http check-before-you-pay https://check.loopholetape.com/mcp
This file is for an operator who would rather run the plug-in on their own machine:
  claude mcp add check-before-you-pay -- python3 /path/to/mcp_server.py
It needs the file mcp_http.py beside it, which holds the tools' descriptions and answers for both ways of reaching
the plug-in. The option --base URL reads another copy of the site, such as a preview on a home network.
A self-test without any client: python3 -I mcp_server.py --selftest   (it exits with status 1 if anything is off)

It speaks both kinds of protocol revision, as mcp_http.py explains: a request that names its protocol version in
params._meta is answered by the rules of 2026-07-28, and a client that opens with initialize is answered by the
rules of the revision it asks for (2025-11-25, 2025-06-18, 2025-03-26 or 2024-11-05).
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcp_http as core  # noqa: E402

BASE = core.SITE_URL
VERSION = core.VERSION
TOOLS = core.TOOLS
AGENT = 'check-before-you-pay-plugin/%s' % VERSION


def fetch(path):
    """one page of the site: (200, text), (404, '') when the site has no such page, (None, reason) when it did not answer"""
    try:
        req = urllib.request.Request(BASE + path, headers={'User-Agent': AGENT})
        with urllib.request.urlopen(req, timeout=20) as r:
            return (200, r.read(core.MAX_FILE).decode('utf-8', 'replace')) if r.status == 200 else (None, 'it answered with status %d' % r.status)
    except urllib.error.HTTPError as e:
        return (404, '') if e.code == 404 else (None, 'it answered with status %d' % e.code)
    except (urllib.error.URLError, OSError, ValueError) as e:
        return None, 'it did not answer: %s' % str(getattr(e, 'reason', e))[:120]


def handle(msg):
    """One message from the client -> the list of messages to write back (none for a notification)."""
    kind = core.shape(msg)
    if kind is None:
        return [core.error(core.NOID, -32600, 'Invalid request: this is not a JSON-RPC 2.0 request or notification.')]
    if kind != 'request':
        return []                        # a notification such as notifications/initialized, or a stray response
    meta = core.meta_of(msg)
    if core.META_VERSION in meta:
        named = meta[core.META_VERSION]
        if not isinstance(named, str):
            return [core.error(msg['id'], -32602, 'The protocol version in params._meta has to be a string such as "%s".' % core.MODERN[0])]
        if named in core.MODERN:
            return core.modern(msg, fetch)[1]
        if named not in core.LEGACY:
            return [core.unsupported(msg['id'], named[:40])]
    return [core.legacy(msg, fetch)]


def selftest():
    """Runs every method once against the site at BASE and prints one line each. Returns the number of things that were off."""
    off = 0
    new = {'_meta': {core.META_VERSION: core.MODERN[0], core.META_CAPABILITIES: {}, core.META_CLIENT: {'name': 'selftest', 'version': VERSION}}}

    def said(label, replies, want):
        nonlocal off
        if not replies:
            good, note = want == 'nothing', '(no reply, as it should be)'
        else:
            r = replies[-1]
            if 'error' in r:
                good, note = want == 'error', 'error %s: %s' % (r['error']['code'], r['error']['message'][:110])
            elif 'content' in r['result']:
                t = r['result']['content'][0]['text']
                good = want == ('refusal' if r['result']['isError'] else 'answer')
                note = 'isError=%s | %d characters | %s' % (r['result']['isError'], len(t), t[:120].replace('\n', ' '))
            else:
                good, note = want == 'result', json.dumps(r['result'])[:150]
        off += 0 if good else 1
        print('%-34s %s %s' % (label, 'ok ' if good else 'OFF', note))

    said('initialize (2025-11-25)', handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'selftest', 'version': VERSION}}}), 'result')
    said('notifications/initialized', handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}), 'nothing')
    said('ping', handle({'jsonrpc': '2.0', 'id': 2, 'method': 'ping'}), 'result')
    said('tools/list', handle({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/list'}), 'result')
    said('check_contest 92', handle({'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'check_contest', 'arguments': {'netuid': 92}}}), 'answer')
    said('check_contest 80 (no page)', handle({'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call', 'params': {'name': 'check_contest', 'arguments': {'netuid': 80}}}), 'answer')
    said('check_wallet not-a-wallet', handle({'jsonrpc': '2.0', 'id': 6, 'method': 'tools/call', 'params': {'name': 'check_wallet', 'arguments': {'coldkey': 'not-a-wallet'}}}), 'refusal')
    said('list_contests', handle({'jsonrpc': '2.0', 'id': 7, 'method': 'tools/call', 'params': {'name': 'list_contests', 'arguments': {}}}), 'answer')
    said('a tool that does not exist', handle({'jsonrpc': '2.0', 'id': 8, 'method': 'tools/call', 'params': {'name': 'no_such_tool', 'arguments': {}}}), 'error')
    said('server/discover (2026-07-28)', handle({'jsonrpc': '2.0', 'id': 9, 'method': 'server/discover', 'params': dict(new)}), 'result')
    said('tools/list (2026-07-28)', handle({'jsonrpc': '2.0', 'id': 10, 'method': 'tools/list', 'params': dict(new)}), 'result')
    said('check_contest 26 (2026-07-28)', handle({'jsonrpc': '2.0', 'id': 11, 'method': 'tools/call', 'params': dict(new, name='check_contest', arguments={'netuid': 26})}), 'answer')
    said('a version nobody speaks', handle({'jsonrpc': '2.0', 'id': 12, 'method': 'tools/list', 'params': {'_meta': {core.META_VERSION: '1900-01-01', core.META_CAPABILITIES: {}}}}), 'error')
    print('self-test against %s: %s' % (BASE, 'everything answered as it should' if not off else '%d of the lines above are off' % off))
    return off


def main():
    global BASE
    a = sys.argv[1:]
    if '--base' in a:
        BASE = a[a.index('--base') + 1].rstrip('/') + '/'
    if not BASE.startswith(('https://', 'http://')):
        sys.exit('The base has to be the http or https address the site is served from.')
    if '--selftest' in a:
        sys.exit(1 if selftest() else 0)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except (ValueError, RecursionError):
            out = [core.error(core.NOID, -32700, 'Parse error: this line is not valid JSON.')]
        else:
            if isinstance(msg, list):        # a batch, which only clients of 2025-03-26 send: one array comes back
                many = [r for one in msg[:core.MAX_BATCH] for r in handle(one)]
                out = [many] if many else []
            else:
                out = handle(msg)
        for reply in out:
            sys.stdout.write(json.dumps(reply) + '\n')
            sys.stdout.flush()


if __name__ == '__main__':
    main()
