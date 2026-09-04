#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub MCP server (stdio, JSON-RPC 2.0) - zero third-party dependencies.
Talks to the GitHub REST API v3.

Routing note: on this machine the local proxy (127.0.0.1:1088) needs 15-17s
for the TLS handshake and fails often, while a direct connection to
api.github.com completes in 1-3s. So: direct first, proxy as fallback.
"""
import sys
import os
import json
import base64
import urllib.request
import urllib.error
import urllib.parse
import time

TOKEN = os.environ.get('GITHUB_TOKEN', '')
API = 'https://api.github.com'

# opener that ignores proxy env vars, and one that honours them
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
VIA_PROXY = urllib.request.build_opener()


def _do(opener, method, url, body):
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header('Authorization', 'Bearer ' + TOKEN)
    req.add_header('Accept', 'application/vnd.github+json')
    req.add_header('X-GitHub-Api-Version', '2022-11-28')
    req.add_header('User-Agent', 'wb-github-mcp/1.0')
    if body is not None:
        req.add_header('Content-Type', 'application/json')
    with opener.open(req, timeout=25) as r:
        blob = r.read()
        if not blob:
            return {'ok': True, 'status': r.status}
        try:
            return json.loads(blob.decode('utf-8'))
        except ValueError:
            return {'ok': True, 'status': r.status, 'raw': blob.decode('utf-8', 'replace')[:500]}


def api(method, path, data=None):
    url = path if path.startswith('http') else API + path
    body = json.dumps(data).encode('utf-8') if data is not None else None
    last = None
    for attempt in range(3):
        for opener in (DIRECT, VIA_PROXY):
            try:
                return _do(opener, method, url, body)
            except urllib.error.HTTPError as e:
                msg = e.read().decode('utf-8', 'replace')[:600]
                if 400 <= e.code < 500:  # a real answer, not worth retrying
                    return {'error': True, 'status': e.code, 'message': msg}
                last = 'HTTP %s: %s' % (e.code, msg)
            except Exception as e:
                last = '%s: %s' % (type(e).__name__, e)
        time.sleep(0.5)
    return {'error': True, 'message': last}


def txt(obj):
    if isinstance(obj, str):
        s = obj
    else:
        s = json.dumps(obj, ensure_ascii=False, indent=2)
    if len(s) > 20000:
        s = s[:20000] + '\n... [truncated]'
    return {'content': [{'type': 'text', 'text': s}], 'isError': bool(isinstance(obj, dict) and obj.get('error'))}


# ---------------------------------------------------------------- helpers

def _b64(content):
    return base64.b64encode(content.encode('utf-8')).decode('ascii')


def _decode_file(d):
    out = {k: d.get(k) for k in ('name', 'path', 'sha', 'size', 'type')}
    enc = d.get('encoding')
    if enc == 'base64' and d.get('content'):
        try:
            out['content'] = base64.b64decode(d['content']).decode('utf-8', 'replace')
        except Exception:
            out['content'] = '<binary or undecodable>'
    return out


def _slim_repo(r):
    return {
        'full_name': r.get('full_name'),
        'private': r.get('private'),
        'description': r.get('description'),
        'default_branch': r.get('default_branch'),
        'html_url': r.get('html_url'),
        'updated_at': r.get('updated_at'),
        'stargazers_count': r.get('stargazers_count'),
        'language': r.get('language'),
    }


def _slim_issue(i):
    return {
        'number': i.get('number'),
        'title': i.get('title'),
        'state': i.get('state'),
        'user': (i.get('user') or {}).get('login'),
        'created_at': i.get('created_at'),
        'html_url': i.get('html_url'),
        'body': (i.get('body') or '')[:2000],
    }


def _slim_pr(p):
    return {
        'number': p.get('number'),
        'title': p.get('title'),
        'state': p.get('state'),
        'user': (p.get('user') or {}).get('login'),
        'head': (p.get('head') or {}).get('ref'),
        'base': (p.get('base') or {}).get('ref'),
        'html_url': p.get('html_url'),
        'merged': p.get('merged'),
    }


def _slim_commit(c):
    return {
        'sha': c.get('sha'),
        'author': ((c.get('commit') or {}).get('author') or {}).get('name'),
        'date': ((c.get('commit') or {}).get('author') or {}).get('date'),
        'message': ((c.get('commit') or {}).get('message') or '').split('\n')[0][:300],
    }


# ---------------------------------------------------------------- tools

def t_whoami(a):
    return txt(api('GET', '/user'))


def t_list_repos(a):
    per = int(a.get('per_page', 30))
    typ = a.get('type', 'all')
    r = api('GET', '/user/repos?per_page=%d&sort=updated&type=%s' % (per, typ))
    if isinstance(r, list):
        return txt([_slim_repo(x) for x in r])
    return txt(r)


def t_get_repo(a):
    return txt(api('GET', '/repos/%s/%s' % (a['owner'], a['repo'])))


def t_create_repo(a):
    body = {'name': a['name']}
    if a.get('description'):
        body['description'] = a['description']
    body['private'] = bool(a.get('private', False))
    body['auto_init'] = bool(a.get('auto_init', False))
    if a.get('gitignore_template'):
        body['gitignore_template'] = a['gitignore_template']
    r = api('POST', '/user/repos', body)
    if isinstance(r, dict) and not r.get('error'):
        return txt({'created': True, **_slim_repo(r)})
    return txt(r)


def t_delete_repo(a):
    return txt(api('DELETE', '/repos/%s/%s' % (a['owner'], a['repo'])))


def t_list_dir(a):
    path = a.get('path', '')
    ref = a.get('ref')
    q = '/repos/%s/%s/contents/%s' % (a['owner'], a['repo'], urllib.parse.quote(path, safe='/'))
    if ref:
        q += '?ref=' + urllib.parse.quote(ref, safe='')
    r = api('GET', q)
    if isinstance(r, list):
        return txt([{'name': x.get('name'), 'type': x.get('type'), 'size': x.get('size'), 'path': x.get('path')} for x in r])
    return txt(r)


def t_get_file(a):
    q = '/repos/%s/%s/contents/%s' % (a['owner'], a['repo'], urllib.parse.quote(a['path'], safe='/'))
    if a.get('ref'):
        q += '?ref=' + urllib.parse.quote(a['ref'], safe='')
    r = api('GET', q)
    if isinstance(r, dict) and not r.get('error'):
        return txt(_decode_file(r))
    return txt(r)


def t_create_file(a):
    path = a['path']
    q = '/repos/%s/%s/contents/%s' % (a['owner'], a['repo'], urllib.parse.quote(path, safe='/'))
    body = {'message': a.get('message', 'add ' + path), 'content': _b64(a['content'])}
    if a.get('branch'):
        body['branch'] = a['branch']
    existing = api('GET', q + ('?ref=' + urllib.parse.quote(a['branch'], safe='') if a.get('branch') else ''))
    if isinstance(existing, dict) and existing.get('sha'):
        body['sha'] = existing['sha']
    r = api('PUT', q, body)
    if isinstance(r, dict) and not r.get('error'):
        return txt({'ok': True, 'path': (r.get('content') or {}).get('path'), 'commit': (r.get('commit') or {}).get('sha')})
    return txt(r)


def t_delete_file(a):
    q = '/repos/%s/%s/contents/%s' % (a['owner'], a['repo'], urllib.parse.quote(a['path'], safe='/'))
    cur = api('GET', q + ('?ref=' + urllib.parse.quote(a['branch'], safe='') if a.get('branch') else ''))
    if isinstance(cur, dict) and cur.get('error'):
        return txt(cur)
    body = {'message': a.get('message', 'delete ' + a['path']), 'sha': cur.get('sha')}
    if a.get('branch'):
        body['branch'] = a['branch']
    return txt(api('DELETE', q, body))


def t_push_files(a):
    """Create or update many files in one commit-ish loop (one commit per file)."""
    results = []
    for f in a.get('files', []):
        q = '/repos/%s/%s/contents/%s' % (a['owner'], a['repo'], urllib.parse.quote(f['path'], safe='/'))
        body = {'message': a.get('message', 'update files'), 'content': _b64(f['content'])}
        if a.get('branch'):
            body['branch'] = a['branch']
        cur = api('GET', q + ('?ref=' + urllib.parse.quote(a['branch'], safe='') if a.get('branch') else ''))
        if isinstance(cur, dict) and cur.get('sha'):
            body['sha'] = cur['sha']
        r = api('PUT', q, body)
        results.append({'path': f['path'], 'ok': not (isinstance(r, dict) and r.get('error')),
                        'error': r.get('message') if isinstance(r, dict) else None})
    return txt(results)


def t_list_branches(a):
    r = api('GET', '/repos/%s/%s/branches?per_page=100' % (a['owner'], a['repo']))
    if isinstance(r, list):
        return txt([{'name': x.get('name'), 'sha': (x.get('commit') or {}).get('sha')} for x in r])
    return txt(r)


def t_create_branch(a):
    base = a.get('from_branch')
    if not base:
        info = api('GET', '/repos/%s/%s' % (a['owner'], a['repo']))
        base = info.get('default_branch', 'main')
    ref = api('GET', '/repos/%s/%s/git/ref/heads/%s' % (a['owner'], a['repo'], base))
    if isinstance(ref, dict) and ref.get('error'):
        return txt(ref)
    sha = (ref.get('object') or {}).get('sha')
    return txt(api('POST', '/repos/%s/%s/git/refs' % (a['owner'], a['repo']),
                   {'ref': 'refs/heads/' + a['branch'], 'sha': sha}))


def t_list_commits(a):
    q = '/repos/%s/%s/commits?per_page=%d' % (a['owner'], a['repo'], int(a.get('per_page', 20)))
    if a.get('sha') or a.get('branch'):
        q += '&sha=' + urllib.parse.quote(a.get('sha') or a.get('branch'), safe='')
    r = api('GET', q)
    if isinstance(r, list):
        return txt([_slim_commit(x) for x in r])
    return txt(r)


def t_list_issues(a):
    q = '/repos/%s/%s/issues?state=%s&per_page=%d' % (a['owner'], a['repo'], a.get('state', 'open'), int(a.get('per_page', 30)))
    r = api('GET', q)
    if isinstance(r, list):
        return txt([_slim_issue(x) for x in r])
    return txt(r)


def t_create_issue(a):
    body = {'title': a['title']}
    if a.get('body'):
        body['body'] = a['body']
    if a.get('labels'):
        body['labels'] = a['labels'] if isinstance(a['labels'], list) else [a['labels']]
    if a.get('assignees'):
        body['assignees'] = a['assignees'] if isinstance(a['assignees'], list) else [a['assignees']]
    return txt(api('POST', '/repos/%s/%s/issues' % (a['owner'], a['repo']), body))


def t_comment_issue(a):
    return txt(api('POST', '/repos/%s/%s/issues/%s/comments' % (a['owner'], a['repo'], a['issue_number']),
                   {'body': a['body']}))


def t_close_issue(a):
    return txt(api('PATCH', '/repos/%s/%s/issues/%s' % (a['owner'], a['repo'], a['issue_number']),
                   {'state': a.get('state', 'closed')}))


def t_list_prs(a):
    q = '/repos/%s/%s/pulls?state=%s&per_page=%d' % (a['owner'], a['repo'], a.get('state', 'open'), int(a.get('per_page', 30)))
    r = api('GET', q)
    if isinstance(r, list):
        return txt([_slim_pr(x) for x in r])
    return txt(r)


def t_create_pr(a):
    body = {'title': a['title'], 'head': a['head'], 'base': a['base']}
    if a.get('body'):
        body['body'] = a['body']
    body['draft'] = bool(a.get('draft', False))
    return txt(api('POST', '/repos/%s/%s/pulls' % (a['owner'], a['repo']), body))


def t_merge_pr(a):
    body = {}
    if a.get('merge_method'):
        body['merge_method'] = a['merge_method']
    if a.get('commit_title'):
        body['commit_title'] = a['commit_title']
    return txt(api('PUT', '/repos/%s/%s/pulls/%s/merge' % (a['owner'], a['repo'], a['pull_number']), body or None))


def t_search_repos(a):
    q = '/search/repositories?q=%s&per_page=%d' % (urllib.parse.quote(a['query']), int(a.get('per_page', 20)))
    r = api('GET', q)
    if isinstance(r, dict) and isinstance(r.get('items'), list):
        return txt({'total_count': r.get('total_count'), 'items': [_slim_repo(x) for x in r['items']]})
    return txt(r)


def t_search_code(a):
    q = '/search/code?q=%s&per_page=%d' % (urllib.parse.quote(a['query']), int(a.get('per_page', 20)))
    r = api('GET', q)
    if isinstance(r, dict) and isinstance(r.get('items'), list):
        items = [{'path': x.get('path'), 'repo': (x.get('repository') or {}).get('full_name'),
                  'url': x.get('html_url')} for x in r['items']]
        return txt({'total_count': r.get('total_count'), 'items': items})
    return txt(r)


def t_list_notifications(a):
    r = api('GET', '/notifications?per_page=%d' % int(a.get('per_page', 20)))
    if isinstance(r, list):
        return txt([{'id': x.get('id'), 'reason': x.get('reason'), 'unread': x.get('unread'),
                     'title': ((x.get('subject') or {}).get('title')),
                     'repo': (x.get('repository') or {}).get('full_name')} for x in r])
    return txt(r)


def t_run_api(a):
    """Escape hatch: call any GitHub REST endpoint. method + path (+ optional body)."""
    return txt(api(a.get('method', 'GET'), a['path'], a.get('body')))


TOOLS = [
    ('whoami', 'Get the authenticated GitHub user profile and token scopes context.', {'type': 'object', 'properties': {}}, t_whoami),
    ('list_repos', 'List repositories of the authenticated user, most recently updated first.', {'type': 'object', 'properties': {'per_page': {'type': 'integer', 'description': 'Default 30'}, 'type': {'type': 'string', 'description': 'all|owner|public|private|member. Default all'}}}, t_list_repos),
    ('get_repo', 'Get details of a repository.', {'type': 'object', 'properties': {'owner': {'type': 'string'}, 'repo': {'type': 'string'}}, 'required': ['owner', 'repo']}, t_get_repo),
    ('create_repo', 'Create a new repository.', {'type': 'object', 'properties': {'name': {'type': 'string'}, 'description': {'type': 'string'}, 'private': {'type': 'boolean'}, 'auto_init': {'type': 'boolean'}, 'gitignore_template': {'type': 'string'}}, 'required': ['name']}, t_create_repo),
    ('delete_repo', 'Delete a repository. Destructive.', {'type': 'object', 'properties': {'owner': {'type': 'string'}, 'repo': {'type': 'string'}}, 'required': ['owner', 'repo']}, t_delete_repo),
    ('list_dir', 'List files/directories at a path in a repo.', {'type': 'object', 'properties': {'owner': {'type': 'string'}, 'repo': {'type': 'string'}, 'path': {'type': 'string', 'description': 'Directory path, empty for root'}, 'ref': {'type': 'string', 'description': 'Branch/tag/sha'}}, 'required': ['owner', 'repo']}, t_list_dir),
    ('get_file', 'Read a file from a repo (decoded text).', {'type': 'object', 'properties': {'owner': {'type': 'string'}, 'repo': {'type': 'string'}, 'path': {'type': 'string'}, 'ref': {'type': 'string'}}, 'required': ['owner', 'repo', 'path']}, t_get_file),
    ('create_file', 'Create or update a single file (creates a commit).', {'type': 'object', 'properties': {'owner': {'type': 'string'}, 'repo': {'type': 'string'}, 'path': {'type': 'string'}, 'content': {'type': 'string', 'description': 'Full file text'}, 'message': {'type': 'string'}, 'branch': {'type': 'string'}}, 'required': ['owner', 'repo', 'path', 'content']}, t_create_file),
    ('delete_file', 'Delete a file from a repo.', {'type': 'object', 'properties': {'owner': {'type': 'string'}, 'repo': {'type': 'string'}, 'path': {'type': 'string'}, 'message': {'type': 'string'}, 'branch': {'type': 'string'}}, 'required': ['owner', 'repo', 'path']}, t_delete_file),
    ('push_files', 'Create or update many files at once (one commit per file).', {'type': 'object', 'properties': {'owner': {'type': 'string'}, 'repo': {'type': 'string'}, 'files': {'type': 'array', 'items': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'content': {'type': 'string'}}, 'required': ['path', 'content']}}, 'message': {'type': 'string'}, 'branch': {'type': 'string'}}, 'required': ['owner', 'repo', 'files']}, t_push_files),
    ('list_branches', 'List branches of a repo.', {'type': 'object', 'properties': {'owner': {'type': 'string'}, 'repo': {'type': 'string'}}, 'required': ['owner', 'repo']}, t_list_branches),
    ('create_branch', 'Create a branch from another branch (default branch if omitted).', {'type': 'object', 'properties': {'owner': {'type': 'string'}, 'repo': {'type': 'string'}, 'branch': {'type': 'string'}, 'from_branch': {'type': 'string'}}, 'required': ['owner', 'repo', 'branch']}, t_create_branch),
    ('list_commits', 'List recent commits.', {'type': 'object', 'properties': {'owner': {'type': 'string'}, 'repo': {'type': 'string'}, 'branch': {'type': 'string'}, 'sha': {'type': 'string'}, 'per_page': {'type': 'integer'}}, 'required': ['owner', 'repo']}, t_list_commits),
    ('list_issues', 'List issues of a repo.', {'type': 'object', 'properties': {'owner': {'type': 'string'}, 'repo': {'type': 'string'}, 'state': {'type': 'string', 'description': 'open|closed|all'}, 'per_page': {'type': 'integer'}}, 'required': ['owner', 'repo']}, t_list_issues),
    ('create_issue', 'Create an issue.', {'type': 'object', 'properties': {'owner': {'type': 'string'}, 'repo': {'type': 'string'}, 'title': {'type': 'string'}, 'body': {'type': 'string'}, 'labels': {'type': 'array', 'items': {'type': 'string'}}, 'assignees': {'type': 'array', 'items': {'type': 'string'}}}, 'required': ['owner', 'repo', 'title']}, t_create_issue),
    ('comment_issue', 'Comment on an issue or PR.', {'type': 'object', 'properties': {'owner': {'type': 'string'}, 'repo': {'type': 'string'}, 'issue_number': {'type': 'integer'}, 'body': {'type': 'string'}}, 'required': ['owner', 'repo', 'issue_number', 'body']}, t_comment_issue),
    ('close_issue', 'Close or reopen an issue.', {'type': 'object', 'properties': {'owner': {'type': 'string'}, 'repo': {'type': 'string'}, 'issue_number': {'type': 'integer'}, 'state': {'type': 'string', 'description': 'closed|open'}}, 'required': ['owner', 'repo', 'issue_number']}, t_close_issue),
    ('list_prs', 'List pull requests.', {'type': 'object', 'properties': {'owner': {'type': 'string'}, 'repo': {'type': 'string'}, 'state': {'type': 'string'}, 'per_page': {'type': 'integer'}}, 'required': ['owner', 'repo']}, t_list_prs),
    ('create_pr', 'Open a pull request.', {'type': 'object', 'properties': {'owner': {'type': 'string'}, 'repo': {'type': 'string'}, 'title': {'type': 'string'}, 'head': {'type': 'string'}, 'base': {'type': 'string'}, 'body': {'type': 'string'}, 'draft': {'type': 'boolean'}}, 'required': ['owner', 'repo', 'title', 'head', 'base']}, t_create_pr),
    ('merge_pr', 'Merge a pull request.', {'type': 'object', 'properties': {'owner': {'type': 'string'}, 'repo': {'type': 'string'}, 'pull_number': {'type': 'integer'}, 'merge_method': {'type': 'string', 'description': 'merge|squash|rebase'}, 'commit_title': {'type': 'string'}}, 'required': ['owner', 'repo', 'pull_number']}, t_merge_pr),
    ('search_repos', 'Search repositories on GitHub.', {'type': 'object', 'properties': {'query': {'type': 'string', 'description': 'e.g. "language:python stars:>1000 topic:embedded"'}, 'per_page': {'type': 'integer'}}, 'required': ['query']}, t_search_repos),
    ('search_code', 'Search code across GitHub.', {'type': 'object', 'properties': {'query': {'type': 'string'}, 'per_page': {'type': 'integer'}}, 'required': ['query']}, t_search_code),
    ('list_notifications', 'List notifications for the authenticated user.', {'type': 'object', 'properties': {'per_page': {'type': 'integer'}}, }, t_list_notifications),
    ('run_api', 'Escape hatch: call any GitHub REST endpoint. Path examples: /user/repos, /repos/{owner}/{repo}/contents/{path}.', {'type': 'object', 'properties': {'method': {'type': 'string'}, 'path': {'type': 'string'}, 'body': {'type': 'object'}}, 'required': ['path']}, t_run_api),
]

HANDLERS = {}
TOOL_DEFS = []
for _name, _desc, _schema, _fn in TOOLS:
    HANDLERS[_name] = _fn
    TOOL_DEFS.append({'name': _name, 'description': _desc, 'inputSchema': _schema})


def handle(msg):
    m = msg.get('method')
    mid = msg.get('id')
    if m == 'initialize':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {
            'protocolVersion': '2024-11-05',
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': 'github', 'version': '1.0.0'},
        }}
    if m == 'tools/list':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {'tools': TOOL_DEFS}}
    if m == 'tools/call':
        p = msg.get('params') or {}
        name = p.get('name')
        args = p.get('arguments') or {}
        fn = HANDLERS.get(name)
        if not fn:
            return {'jsonrpc': '2.0', 'id': mid, 'result': txt({'error': True, 'message': 'unknown tool: %s' % name})}
        try:
            res = fn(args)
        except Exception as e:
            res = txt({'error': True, 'message': '%s: %s' % (type(e).__name__, e)})
        return {'jsonrpc': '2.0', 'id': mid, 'result': res}
    if m == 'ping':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {}}
    if m == 'resources/list':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {'resources': []}}
    if m == 'prompts/list':
        return {'jsonrpc': '2.0', 'id': mid, 'result': {'prompts': []}}
    if m and m.startswith('notifications/'):
        return None
    if mid is not None:
        return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': 'method not found: %s' % m}}
    return None


def main():
    if not TOKEN:
        sys.stderr.write('GITHUB_TOKEN not set\n')
    out = sys.stdout
    for line in sys.stdin.buffer:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode('utf-8'))
        except ValueError:
            continue
        try:
            resp = handle(msg)
        except Exception as e:
            resp = {'jsonrpc': '2.0', 'id': msg.get('id'),
                    'error': {'code': -32603, 'message': '%s: %s' % (type(e).__name__, e)}}
        if resp is None:
            continue
        out.write(json.dumps(resp, ensure_ascii=False) + '\n')
        out.flush()


if __name__ == '__main__':
    main()
