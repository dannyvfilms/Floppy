#!/usr/bin/env python3
"""Expo build dashboard: page -> component tree with native, sharing and sign-off status.

    python3 scripts/expo_dashboard.py --serve    # live view of branch `latest` at http://127.0.0.1:8765
    python3 scripts/expo_dashboard.py            # write .floppy/expo-dashboard.html and open it
    python3 scripts/expo_dashboard.py --ref X    # another branch, tag or commit
    python3 scripts/expo_dashboard.py --worktree # the files on disk in this checkout instead of a ref
    python3 scripts/expo_dashboard.py --fetch    # `git fetch` the ref's remote at most once a minute first

Reads the code (imports and JSX under expo/ and frontend/), the page registry
(frontend/pages/registry.js), docs/ui/architecture-registry.json (agent-recorded verification)
and docs/ui/component-register.md (owner sign-off). A file counts as signed off when a
`- Sign-off:` line in the register lists it; the format is in docs/ui/expo-dashboard.md.
Standard library only; nothing is written.
"""
import argparse, collections, http.server, json, os, re, subprocess, sys, threading, time, webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'expo_dashboard.template.html')
OUT = os.path.join(ROOT, '.floppy', 'expo-dashboard.html')

LABELS = dict(home='Home', discover='Discover', library='Library', search='Search', detail='Detail', people='People', music='Music', collection='Collection', lists='Lists', listDetail='List detail', tags='Tags', history='History', statistics='Statistics', calendar='Release calendar', settings='Settings shell', settingsAccount='Account', settingsPreferences='Preferences', settingsNotifications='Notifications', settingsAppearance='Appearance', settingsCards='Media cards', settingsHome='Home screen', settingsData='Data management', settingsAccess='Access & tokens', settingsUsers='Users', settingsSidebar='Sidebar', settingsAbout='About', settingsAdvanced='Advanced', providers='Providers', providerDetail='Provider detail', auth='Sign in', onboarding='Onboarding', errors='Errors & API docs', connections='Connections', metadataReview='Metadata review', utilities='Utilities')
GROUPS = [('Browse', ['home', 'discover', 'library', 'search', 'detail', 'people', 'music']), ('Collections', ['collection', 'lists', 'listDetail', 'tags']), ('Activity', ['history', 'statistics', 'calendar']), ('Settings', ['settings', 'settingsAccount', 'settingsPreferences', 'settingsNotifications', 'settingsAppearance', 'settingsCards', 'settingsHome', 'settingsData', 'settingsAccess', 'settingsUsers', 'settingsSidebar', 'settingsAbout', 'settingsAdvanced']), ('Account & setup', ['auth', 'onboarding', 'providers', 'providerDetail', 'connections', 'metadataReview', 'utilities', 'errors'])]
EXTS_N = ['.native.jsx', '.ios.jsx', '.native.js', '.ios.js', '.jsx', '.js', '.mjs', '.tsx', '.ts']
EXTS_W = ['.web.jsx', '.web.js', '.jsx', '.js', '.mjs', '.tsx', '.ts']
SRC_EXT = re.compile(r'\.(jsx?|mjs|tsx?)$')
VARIANT = re.compile(r'\.(native|ios|web)(?=\.\w+$)')
IMPORT = re.compile(r"(?:import|export)\s[^'\"]*?from\s*['\"]([^'\"]+)['\"]|import\s*['\"]([^'\"]+)['\"]|require\(\s*['\"]([^'\"]+)['\"]\s*\)|import\(\s*['\"]([^'\"]+)['\"]\s*\)", re.S)


def git(*args, text=True):
    out = subprocess.run(['git', '-C', ROOT, *args], capture_output=True, text=text)
    if out.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {(out.stderr if text else out.stderr.decode()).strip()}")
    return out.stdout


class Source:
    """Files of a git ref (blob contents cached by sha, so a rescan only reads what changed) or of the checkout."""
    blobs = {}

    def __init__(self, ref):
        self.ref = ref
        if ref:
            self.commit = git('rev-parse', '--verify', ref + '^{commit}').strip()
            self.index = {}
            for line in git('ls-tree', '-r', '-z', self.commit).split('\0'):
                if line:
                    meta, path = line.split('\t', 1)
                    self.index[path] = meta.split()[2]
            info = git('log', '-1', '--format=%h|%cd|%s', '--date=format:%b %d %H:%M', self.commit).strip().split('|', 2)
            self.label = f'{ref} @ {info[0]} ({info[1]}) {info[2][:70]}'
        else:
            self.commit = 'worktree'
            self.index = None
            self.label = 'working tree of this checkout (uncommitted changes included)'

    def isfile(self, path):
        return path in self.index if self.ref else os.path.isfile(os.path.join(ROOT, path))

    def read(self, path):
        if not self.ref:
            return open(os.path.join(ROOT, path), errors='ignore').read()
        sha = self.index[path]
        if sha not in Source.blobs:
            Source.blobs[sha] = Source.cat(sha)
        return Source.blobs[sha]

    batch = None
    lock = threading.Lock()

    @staticmethod
    def cat(sha):
        """One long-lived `git cat-file --batch` process: a cold scan reads ~300 blobs in well under a second."""
        with Source.lock:
            if Source.batch is None or Source.batch.poll() is not None:
                Source.batch = subprocess.Popen(['git', '-C', ROOT, 'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            Source.batch.stdin.write(sha.encode() + b'\n')
            Source.batch.stdin.flush()
            header = Source.batch.stdout.readline().split()
            size = int(header[2])
            body = Source.batch.stdout.read(size)
            Source.batch.stdout.read(1)
            return body.decode('utf-8', 'ignore')

    def under(self, prefix):
        if self.ref:
            return [p for p in self.index if p.startswith(prefix)]
        return [os.path.relpath(os.path.join(dp, n), ROOT) for dp, _, fs in os.walk(os.path.join(ROOT, prefix)) for n in fs]


def stem_of(path):
    return SRC_EXT.sub('', VARIANT.sub('', path))


def load_pages(source):
    src = source.read('frontend/pages/registry.js')
    body = src.split('export const pages = {')[1].split('\n};')[0]
    pages = []
    for entry in re.split(r"\n  (?=\w+: \{)", '\n' + body):
        entry = entry.strip()
        if not entry:
            continue
        page = {'key': entry.split(':')[0]}
        for k in ['id', 'webRoute', 'nativeScreen', 'nativeAdapter', 'view', 'webAdapter', 'status']:
            m = re.search(r"\b%s:\s*(?:'([^']*)'|null)" % k, entry)
            if m:
                page[k] = m.group(1)
        pages.append(page)
    return pages


class Scan:
    def __init__(self, source):
        self.src = source
        self.pages = load_pages(source)
        self.cache = {}
        self.stop = {p['nativeScreen'] for p in self.pages}
        registry = json.loads(source.read('docs/ui/architecture-registry.json'))
        self.reg = {}
        for section in ('universal', 'platform', 'logic'):
            for path, v in registry.get(section, {}).items():
                self.reg[path] = v

    def signoffs(self):
        """`- Sign-off:` lines of the component register: date, who, covered files, per-platform evidence."""
        out = {}
        for m in re.finditer(r'^- Sign-off:\s*(.+)$', self.src.read('docs/ui/component-register.md'), re.M):
            line = m.group(1)
            date = re.search(r'\d{4}-\d{2}-\d{2}', line)
            who = re.search(r'\d{4}-\d{2}-\d{2},\s*([^.`]+?)\.', line)
            evidence = ' · '.join(f'{k}: {v.strip()}' for k, v in re.findall(r'\b(Web|iOS|Android):\s*([^.]+)\.', line))
            for f in re.findall(r'`([^`\s]+/[^`\s]+\.(?:jsx?|mjs|tsx?))`', line):
                if f not in out or (date and date.group(0) >= (out[f]['date'] or '')):
                    out[f] = dict(by=who.group(1) if who else '', date=date.group(0) if date else '', note=evidence)
        return out

    def resolve(self, frm, spec, plat):
        if not spec.startswith('.'):
            return None
        base = os.path.normpath(os.path.join(os.path.dirname(frm), spec))
        if SRC_EXT.search(base) and self.src.isfile(base):  # an explicit extension names that exact file (how .native wrappers import their shared base)
            return base
        stem = SRC_EXT.sub('', base) if SRC_EXT.search(base) and self.src.isfile(base) else base
        exts = EXTS_N if plat == 'n' else EXTS_W
        for e in exts:
            if self.src.isfile(stem + e):
                return stem + e
        for e in exts:
            if self.src.isfile(os.path.join(stem, 'index' + e)):
                return os.path.join(stem, 'index' + e)
        return None

    def info(self, f):
        if f in self.cache:
            return self.cache[f]
        raw = self.src.read(f)
        specs = [next(g for g in m.groups() if g) for m in IMPORT.finditer(raw)]
        external = {s for s in specs if not s.startswith('.')}
        t = re.sub(r'/\*.*?\*/', '', raw, flags=re.S)
        t = re.sub(r'(?m)^\s*//.*$', '', t)
        loc = sum(1 for l in t.split('\n') if l.strip())
        rn = any(s == 'react-native' or s.startswith('react-native-svg') for s in external)
        dom = bool(re.search(r"className\s*=|dangerouslySetInnerHTML|<(div|span|button|a|img|input|ul|li|section|p|h[1-6]|form|label|select|table|tr|td|svg|path|nav|header|footer|textarea)[\s>/]", t)) or bool(re.search(r"\b(document|window|localStorage)\.", t))
        jsx = bool(re.search(r"</?[A-Za-z][\w.]*[\s/>]", t)) and f.endswith('x')
        if f.endswith('.test.mjs'):
            kind = 'test'
        elif not jsx:
            kind = 'logic'
        elif rn and not dom:
            kind = 'rn'
        elif dom and not rn:
            kind = 'dom'
        elif rn and dom:
            kind = 'mixed'
        else:
            kind = 'neutral'
        self.cache[f] = dict(specs=specs, loc=loc, kind=kind)
        return self.cache[f]

    def closure(self, roots, plat):
        seen = {}
        queue = [(r, None, 0) for r in roots if r]
        while queue:
            f, parent, depth = queue.pop(0)
            if f in seen:
                continue
            seen[f] = (parent, depth)
            if f in self.stop and f not in roots:
                continue
            for s in self.info(f)['specs']:
                r = self.resolve(f, s, plat)
                if r and r not in seen and 'node_modules' not in r and not r.endswith('.test.mjs'):
                    queue.append((r, f, depth + 1))
        return seen

    def entry(self, f):
        return self.reg.get(f) or self.reg.get(stem_of(f) + '.jsx') or self.reg.get(stem_of(f) + '.js')

    def build(self):
        web_roots = [p for p in self.src.under('frontend/') if re.match(r"mount.*\.jsx$|.*\.web\.jsx?$|index\.js$", os.path.basename(p))]
        web = self.closure(web_roots, 'w')
        web_stems = {stem_of(f) for f in web}
        settings_screen = 'expo/app/screens/SettingsScreen.jsx'
        for p in self.pages:
            roots = [p.get('nativeAdapter') or p.get('nativeScreen')]
            if p['key'].startswith('settings') and p['key'] != 'settings' and not p.get('nativeAdapter'):
                roots = [p['nativeScreen']] if p['nativeScreen'] != settings_screen else []
            if p.get('view') and self.src.isfile(p['view']) and p['status'] == 'shared':
                roots.append(p['view'])
            p['roots'] = [r for r in roots if r]
            p['closure'] = self.closure(p['roots'], 'n')
        signoffs = self.signoffs()
        if self.src.ref:  # a file changed on a later day than its sign-off needs a new review
            for f, so in signoffs.items():
                if so['date'] and f in self.src.index:
                    last = git('log', '-1', '--format=%cs', self.src.commit, '--', f).strip()
                    so['stale'] = last > so['date']
                    so['changed'] = last
        usage = collections.defaultdict(set)
        for p in self.pages:
            for f in p['closure']:
                usage[f].add(p['key'])
        files, idx = [], {}
        for p in self.pages:
            for f in p['closure']:
                if f in idx or self.info(f)['kind'] == 'test':
                    continue
                i = self.info(f)
                stem = stem_of(f)
                variants = sorted(s for s in (stem + e for e in ['.web.jsx', '.native.jsx', '.ios.jsx', '.jsx']) if self.src.isfile(s) and s != f)
                layer = 'frontend' if f.startswith('frontend/') else next((n for k, n in [('/surfaces/', 'native-surface'), ('/screens/', 'native-screen'), ('/data/', 'native-data'), ('/components/', 'native-component')] if k in f), 'native-app')
                on_web = f in web or stem in web_stems
                if layer == 'frontend':
                    own = 'shared' if on_web or any('.web.' in v for v in variants) else 'shared-native-only'
                else:
                    own = 'native-unique' if len(usage[f]) <= 1 else 'native-reused'
                e = self.entry(f)
                v = e['verification'] if e else None
                idx[f] = len(files)
                files.append([f, i['kind'], i['loc'], layer, own, int(on_web), len(usage[f]), (e or {}).get('register') or '',
                              [v[k]['status'] for k in ('web', 'ios', 'android')] if v else None,
                              [v[k]['evidence'] for k in ('web', 'ios', 'android')] if v else None,
                              (e or {}).get('purpose') or '', variants, sorted(usage[f]), signoffs.get(f)])
        pages = {}
        for p in self.pages:
            pages[p['key']] = dict(label=LABELS.get(p['key'], p['key']), route=p['webRoute'], status=p['status'], serverOwned=not p.get('webAdapter'), screen=p['nativeScreen'], adapter=p.get('nativeAdapter'), view=p.get('view'), webAdapter=p.get('webAdapter'),
                                   f=[[idx[f], d, idx.get(par, -1) if par else -1] for f, (par, d) in p['closure'].items() if f in idx])
        known = {k for _, ks in GROUPS for k in ks}
        groups = [dict(name=n, pages=[k for k in ks if k in pages]) for n, ks in GROUPS]
        extra = [k for k in pages if k not in known]
        if extra:
            groups.append(dict(name='Other', pages=extra))
        return dict(generated=__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M'), source=self.src.label, unplaced=sorted(f for f in signoffs if f not in idx and stem_of(f) not in {stem_of(t) for t in idx}), groups=groups, pages=pages, files=files)


def render(data):
    html = open(TEMPLATE).read()
    return html.replace('/*DATA*/null', json.dumps(data, separators=(',', ':')).replace('</', '<\\/'))


_cache = {'key': None, 'data': None, 'fetched': 0.0}


def current(args):
    """Scan the ref (or checkout); a branch that has not moved since the last scan reuses it."""
    ref = None if args.worktree else args.ref
    if ref and args.fetch and time.time() - _cache['fetched'] > 60:
        _cache['fetched'] = time.time()
        remote = git('config', '--get', f'branch.{ref}.remote').strip() or 'origin'
        try:
            git('fetch', '--quiet', remote, ref)
            git('branch', '-f', ref, 'FETCH_HEAD') if git('rev-parse', '--abbrev-ref', 'HEAD').strip() != ref and not _checked_out(ref) else None
        except RuntimeError as e:
            print(f'fetch skipped: {e}', file=sys.stderr)
    source = Source(ref)
    key = source.commit if ref else None
    if key is None or key != _cache['key']:
        _cache.update(key=key, data=Scan(source).build())
    return _cache['data']


def _checked_out(ref):
    return any(l == f'branch refs/heads/{ref}' for l in git('worktree', 'list', '--porcelain').split('\n'))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--serve', action='store_true', help='serve a live view on localhost; the page re-checks every few seconds')
    ap.add_argument('--ref', default='latest', help='branch, tag or commit to read (default: latest)')
    ap.add_argument('--worktree', action='store_true', help='read the files on disk in this checkout instead of a git ref')
    ap.add_argument('--fetch', action='store_true', help='fetch the ref from its remote (at most once a minute) before scanning')
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--no-open', action='store_true')
    args = ap.parse_args()
    if not args.serve:
        data = current(args)
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        open(OUT, 'w').write(render(data))
        signed = sum(1 for f in data['files'] if f[13])
        print(f"{OUT}\n{data['source']}\n{len(data['pages'])} pages, {len(data['files'])} files, {signed} signed off")
        if not args.no_open:
            webbrowser.open('file://' + OUT)
        return

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                data = current(args)
                is_json = self.path.startswith('/data.json')
                body, ctype = (json.dumps(data) if is_json else render(data)).encode(), 'application/json' if is_json else 'text/html; charset=utf-8'
                self.send_response(200)
            except Exception as e:  # show the failure in the browser instead of a dead tab
                body, ctype = f'scan failed: {e}'.encode(), 'text/plain'
                self.send_response(500)
            self.send_header('Content-Type', ctype)
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    url = f'http://127.0.0.1:{args.port}'
    print(f'Expo dashboard of {args.ref if not args.worktree else "the working tree"} at {url} (Ctrl+C to stop)')
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
