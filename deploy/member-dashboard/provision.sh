#!/bin/bash
# Member dashboard server setup (TODO #121 Phase C). Run as root. Safe to re-run:
# existing users, keys, databases and the denial journal are kept, never recreated.
# Services listen on 127.0.0.1 only; the public site is nginx on 443 for $DOMAIN (step 10).
set -euo pipefail
REPO=/home/openclaw/.openclaw/workspace
OPT=/opt/member-dashboard
ETC=/etc/member-dashboard
LIB=/var/lib/member-dashboard
PY=$OPT/venv/bin/python
DAILY_USD=${DAILY_USD:-3}
DOMAIN=${DOMAIN:-akash.ignorelist.com}

# 1. One system user per role (no login shell, no home).
for user in md-api md-supervisor md-compute md-quota md-authority md-archive md-frontend; do
  id "$user" >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin "$user"
done

# 2. Release: code + Python env + website build already in $OPT (see README). Read-only for roles.
[ -x "$PY" ] && [ -d "$OPT/current/member_dashboard" ] && [ -d "$OPT/current/web/member-dashboard/.next" ] \
  || { echo "release missing: build $OPT first (README 'Release')" >&2; exit 1; }
mkdir -p "$OPT/node/bin" && ln -sfn /usr/bin/node "$OPT/node/bin/node"
chown -R root:root "$OPT" && chmod -R u=rwX,go=rX "$OPT"
install -d -o md-frontend -g md-frontend -m 0700 "$OPT/current/web/member-dashboard/.next/cache"

# 3. State folders. The web database is shared by api/supervisor/compute through ACLs.
install -d -o root -g root -m 0755 "$LIB"
install -d -o md-api -g md-api -m 0770 "$LIB/web"
setfacl -m u:md-supervisor:rwx,u:md-compute:rwx "$LIB/web"
setfacl -d -m u::rw,u:md-api:rw,u:md-supervisor:rw,u:md-compute:rw,g::---,o::--- "$LIB/web"
# SQLite creates files 0644 minus umask (0640), which would cap the ACLs at read-only;
# a pre-created 0660 file fixes it, and SQLite copies its mode onto -wal/-shm.
[ -e "$LIB/web/web.sqlite3" ] || install -o md-api -g md-api -m 0660 /dev/null "$LIB/web/web.sqlite3"
chmod 0660 "$LIB/web/web.sqlite3"
install -d -o md-quota -g md-quota -m 0700 "$LIB/quota"
install -d -o md-authority -g md-authority -m 0700 "$LIB/denials"
install -d -o md-authority -g md-authority -m 0700 /var/lib/member-dashboard-high-water
install -d -o md-archive -g md-archive -m 0700 "$LIB/archives"
install -d -o md-compute -g md-compute -m 0700 "$LIB/schwab"

# 4. Socket folders (recreated at boot by tmpfiles). Clients get traverse + socket rw by ACL only.
cat > /etc/tmpfiles.d/member-dashboard.conf <<'EOF'
d /run/member-dashboard-authority 0750 md-authority md-authority -
a+ /run/member-dashboard-authority - - - - u:md-api:--x,u:md-supervisor:--x,u:md-compute:--x,m::r-x,d:u:md-api:rw-,d:u:md-supervisor:rw-,d:u:md-compute:rw-
d /run/member-dashboard-quota 0750 md-quota md-quota -
a+ /run/member-dashboard-quota - - - - u:md-supervisor:--x,u:md-compute:--x,m::r-x,d:u:md-supervisor:rw-,d:u:md-compute:rw-
EOF
systemd-tmpfiles --create /etc/tmpfiles.d/member-dashboard.conf

# 5. Read-only access to the bot database for md-supervisor: traverse the workspace
#    (no listing) and read consensus.db*. The default entry covers -wal/-shm that SQLite
#    recreates; the supervisor unit only sees this folder through a read-only bind.
setfacl -n -m u:md-supervisor:--x,m::--x "$REPO"
setfacl -d -m u:md-supervisor:r-- "$REPO"
for f in "$REPO"/consensus.db "$REPO"/consensus.db-wal "$REPO"/consensus.db-shm; do
  [ -e "$f" ] && setfacl -m u:md-supervisor:r-- "$f"
done

# 6. Keys and configs. The OpenRouter key is copied by Python straight from the bot's env
#    file into a compute-only file; it is never printed. Only its length and hash are shown.
install -d -o root -g root -m 0755 "$ETC"
install -d -o root -g root -m 0711 "$ETC/providers"
DAILY_USD="$DAILY_USD" DOMAIN="$DOMAIN" python3 - <<'EOF'
import hashlib, json, os, pwd, secrets, time
from pathlib import Path
ETC = Path('/etc/member-dashboard')
uid = {name: pwd.getpwnam(name).pw_uid for name in
       ('md-api', 'md-supervisor', 'md-compute', 'md-quota', 'md-authority', 'md-archive', 'openclaw')}
gid = {'md-compute': pwd.getpwnam('md-compute').pw_gid}

def private(path, owner, data):
    path = Path(path)
    tmp = path.with_name(path.name + '.pending')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(data)
    os.chown(tmp, pwd.getpwnam(owner).pw_uid, pwd.getpwnam(owner).pw_gid)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)

key_file = ETC / 'providers/openrouter.key'
key = None
for line in Path('/root/.openclaw/.env.service').read_text().splitlines():
    if line.startswith('OPENROUTER_API_KEY='):
        key = line.split('=', 1)[1].strip().strip('"').strip("'")
if not key:
    raise SystemExit('OPENROUTER_API_KEY missing from .env.service')
private(key_file, 'md-compute', key.encode('ascii'))
digest = hashlib.sha256(key.encode('ascii')).hexdigest()
print(f'assistant key copied: {len(key)} characters, sha256 {digest[:12]}...')
del key

# Schwab app key/secret for the borrowed-token market data client (never printed).
env = dict(line.split('=', 1) for line in Path('/root/.openclaw/.env.service').read_text().splitlines()
           if '=' in line and not line.startswith('#'))
schwab = {'key': env.get('SCHWAB_APP_KEY', '').strip().strip('"\''), 'secret': env.get('SCHWAB_APP_SECRET', '').strip().strip('"\'')}
if all(schwab.values()):
    private(ETC / 'providers/schwab.json', 'md-compute', json.dumps(schwab).encode())
    print('schwab app credentials copied')
del env, schwab

for name, owner in (('api-signing-key', 'md-api'), ('archive-key', 'md-archive')):
    if not (ETC / name).exists():
        private(ETC / name, owner, secrets.token_bytes(32))

# One verification date shared by the API twin and compute (fingerprints must match).
state = ETC / 'assistant-verified-until'
if not state.exists():
    state.write_text(str(int(time.time()) + 365 * 86400))
verified_until = int(state.read_text())

common = {'web_path': '/var/lib/member-dashboard/web/web.sqlite3',
          'authority_socket': '/run/member-dashboard-authority/authority.sock',
          'authority_uid': uid['md-authority']}
cgroup = '/sys/fs/cgroup/member.slice/member-dashboard.slice/member-dashboard-worker.service/compute'
configs = {
    'api.json': ('md-api', {'role': 'api', 'uid': uid['md-api'], **common,
        'origin': 'https://' + os.environ['DOMAIN'], 'signing_key': str(ETC / 'api-signing-key'),
        'assistant_key_sha256': digest, 'assistant_verified_until': verified_until}),
    'compute.json': ('md-compute', {'role': 'compute', 'uid': uid['md-compute'], **common,
        'assistant_key': str(key_file), 'assistant_verified_until': verified_until,
        'budget_socket': '/run/member-dashboard-quota/budget.sock',
        'schwab_credentials': str(ETC / 'providers/schwab.json'),
        'schwab_state': '/var/lib/member-dashboard/schwab',
        'analysis_settings': str(ETC / 'analysis-settings.json')}),
    'worker.json': ('md-supervisor', {'role': 'supervisor', 'uid': uid['md-supervisor'], **common,
        'market_path': '/run/member-dashboard-market/consensus.db', 'cgroup_root': cgroup,
        'compute_uid': uid['md-compute'], 'compute_gid': gid['md-compute'],
        'compute_config': str(ETC / 'compute.json'),
        'control_socket': '/run/member-dashboard-quota/control.sock', 'quota_uid': uid['md-quota']}),
    'quota.json': ('md-quota', {'role': 'quota', 'uid': uid['md-quota'],
        'quota_path': '/var/lib/member-dashboard/quota/quota.sqlite3',
        'budget_socket': '/run/member-dashboard-quota/budget.sock',
        'control_socket': '/run/member-dashboard-quota/control.sock',
        'supervisor_uid': uid['md-supervisor'], 'compute_uid': uid['md-compute'],
        'bot_uid': uid['openclaw'], 'cgroup_root': cgroup,
        'assistant_daily_usd': float(os.environ['DAILY_USD'])}),
    'authority.json': ('md-authority', {'role': 'authority', 'uid': uid['md-authority'],
        'journal_path': '/var/lib/member-dashboard/denials/journal.sqlite3',
        'anchor_path': '/var/lib/member-dashboard/denials/anchor.json',
        'checkpoint_path': '/var/lib/member-dashboard-high-water/checkpoint.sqlite3',
        'socket_path': '/run/member-dashboard-authority/authority.sock',
        'read_uids': [uid['md-api'], uid['md-supervisor'], uid['md-compute']],
        'write_uids': [uid['md-api'], uid['md-supervisor']]}),
    'archive.json': ('md-archive', {'role': 'archive', 'uid': uid['md-archive'],
        'archive_root': '/var/lib/member-dashboard/archives', 'key_path': str(ETC / 'archive-key'),
        'node_path': '/opt/member-dashboard/node/bin/node'}),
}
# Lets root run `member_dashboard.manage create-admin|recover-admin` at a terminal.
recovery = ETC / 'recovery.json'
recovery.write_text(json.dumps({'allowed_uids': [0], 'service_uid': uid['md-api'],
                                'web_path': '/var/lib/member-dashboard/web/web.sqlite3'}))
os.chown(recovery, 0, 0); os.chmod(recovery, 0o644)
for name, (owner, value) in configs.items():
    private(ETC / name, owner, json.dumps(value, indent=1).encode())
print('configs written:', ', '.join(configs))
EOF

# 6b. Known symbols for ticker search: SEC company + fund ticker lists (public, refreshed on re-run).
python3 - <<'EOF'
import json, os, re, urllib.request
agent = {'User-Agent': 'OpenClaw Signal Engine (ak@openclaw.dev)'}
def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=agent), timeout=60) as r: return json.load(r)
symbols = {}
for row in fetch('https://www.sec.gov/files/company_tickers.json').values():
    symbols[row['ticker'].upper().replace('-', '.')] = 'equity'
funds = fetch('https://www.sec.gov/files/company_tickers_mf.json')
column = funds['fields'].index('symbol')
for row in funds['data']:
    symbols.setdefault(str(row[column]).upper().replace('-', '.'), 'fund')
symbols = {k: v for k, v in symbols.items() if re.fullmatch(r'[A-Z]{1,12}(?:\.[A-Z]{1,3})?', k)}
if len(symbols) < 5000: raise SystemExit('symbol list looks incomplete; kept the old one')
tmp = '/etc/member-dashboard/symbols.json.pending'
with open(tmp, 'w') as out: json.dump(symbols, out, sort_keys=True)
os.chmod(tmp, 0o644); os.replace(tmp, '/etc/member-dashboard/symbols.json')
print(f'symbols: {len(symbols)}')
EOF

# 6c. !all calculation thresholds for the analysis section, exported from the bot's config
#     without secrets (re-run provision.sh after changing config/consensus.yaml).
python3 "$REPO/scripts/member_dashboard_export_settings.py" "$ETC/analysis-settings.json.pending"
chmod 0644 "$ETC/analysis-settings.json.pending" && mv "$ETC/analysis-settings.json.pending" "$ETC/analysis-settings.json"

# 7. First-time state: quota ledger and denial journal (never recreated when present).
cd "$OPT/current"
umask 077
[ -e "$LIB/quota/quota.sqlite3" ] || runuser -u md-quota -- "$PY" -c \
  "from pathlib import Path;from member_dashboard.store import WebStore;WebStore(Path('$LIB/quota/quota.sqlite3')).migrate()"
[ -e "$LIB/denials/journal.sqlite3" ] || runuser -u md-authority -- "$PY" -c \
  "from member_dashboard.authority import DenialJournal,CheckpointStore as C;DenialJournal.create('$LIB/denials/journal.sqlite3','$LIB/denials/anchor.json',checkpoint=C.create('/var/lib/member-dashboard-high-water/checkpoint.sqlite3'))"

# 8. Units (archive timer stays off until backups are owner-approved).
install -m 0644 "$REPO"/deploy/member-dashboard/member-dashboard.slice /etc/systemd/system/
install -m 0644 "$REPO"/deploy/member-dashboard/member-dashboard-{api,worker,authority,frontend,archive}.service /etc/systemd/system/
install -m 0644 "$REPO"/deploy/member-dashboard/quota.service /etc/systemd/system/member-dashboard-quota.service
install -m 0644 "$REPO"/deploy/member-dashboard/journald.conf /etc/systemd/journald@member-dashboard.conf
install -m 0644 "$REPO"/deploy/member-dashboard/member-dashboard-schwab-{sync.service,sync.timer,renew.service} /etc/systemd/system/
install -d -m 0755 "$OPT/deploy" && install -m 0755 "$REPO"/deploy/member-dashboard/schwab-token-sync.py "$OPT/deploy/"
systemctl daemon-reload
systemctl enable --now member-dashboard-schwab-sync.timer >/dev/null
echo "provisioned; start with: systemctl enable --now member-dashboard-{authority,quota,api,worker,frontend}"

# 9. Owner-attested data permissions (owner decision 2026-10-05: provider permissions are the
#    owner's responsibility). Needs the authority service running; skipped when already recorded.
if systemctl is-active --quiet member-dashboard-authority member-dashboard-api; then
  runuser -u md-api -- "$PY" - <<'PYEOF'
import json, time
from pathlib import Path
from member_dashboard.operations import web_store, owner_permissions, BOT_PRODUCT
from member_dashboard.source_policy import SourcePolicy
config = json.loads(Path('/etc/member-dashboard/api.json').read_text())
store = web_store(config)
policy = SourcePolicy(store); policy.denial_journal = store.authority
from member_dashboard.operations import SEC_SOURCE, SEC_PRODUCT, SCHWAB_SOURCE, SCHWAB_PRODUCT
bot = ['bot-' + s for s in ('analyst-views', 'signal-events', 'alert-history', 'decision-snapshots',
                            'ticker-signals', 'research-sections')]
with store.transaction() as con:
    have = {(r[0], r[1]) for r in con.execute('SELECT source_id,product_id FROM source_permissions')}
now = time.time()
wanted = (owner_permissions(bot, BOT_PRODUCT, 'openclaw-bot', 'https://docs.x.com/developer-terms', now)
          + owner_permissions([SEC_SOURCE], SEC_PRODUCT, 'sec', 'https://www.sec.gov/privacy', now)
          + owner_permissions([SCHWAB_SOURCE], SCHWAB_PRODUCT, 'schwab', 'https://developer.schwab.com/', now))
new = [p for p in wanted if (p.source_id, p.product_id) not in have]
for permission in new: policy.record(permission)
print(f'owner data permissions recorded: {len(new)} new, {len(have)} already present')
PYEOF
fi

# 10. Public site: nginx on 443 with the Let's Encrypt certificate (owner approved go-live 2026-10-06).
#     Port 80 stays closed; the certificate's renewal hooks open it only while renewing.
CERT=/etc/letsencrypt/live/$DOMAIN
if [ -s "$CERT/fullchain.pem" ] && command -v nginx >/dev/null; then
  sed -e "s|UNCONFIGURED_AUTHORIZED_HOST|$DOMAIN|" -e "s|UNCONFIGURED_CERTIFICATE_PATH|$CERT/fullchain.pem|" \
      -e "s|UNCONFIGURED_PRIVATE_KEY_PATH|$CERT/privkey.pem|" -e '/^# Not installable/d' \
      "$REPO"/deploy/member-dashboard/https-proxy.conf.template > /etc/nginx/sites-available/member-dashboard
  ln -sf /etc/nginx/sites-available/member-dashboard /etc/nginx/sites-enabled/member-dashboard
  rm -f /etc/nginx/sites-enabled/default
  nginx -t && systemctl reload-or-restart nginx
  ufw allow 443/tcp comment 'member dashboard' >/dev/null
fi
