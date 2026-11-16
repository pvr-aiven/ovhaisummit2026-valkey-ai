#!/usr/bin/env python3
# Signed OVH API v1 call from ~/.ovh.conf. Usage: ovhapi.py METHOD PATH [JSON_BODY] [--secret-out FILE]
# Prints the status and the JSON body; with --secret-out, the "password" field is written to FILE
# (0600) and blanked from the printed body.
import configparser, hashlib, json, os, sys, urllib.error, urllib.request

args = sys.argv[1:]
secret_out = None
if '--secret-out' in args:
    i = args.index('--secret-out'); secret_out = args[i + 1]; del args[i:i + 2]
method, path = args[0], args[1]
body = args[2] if len(args) > 2 else ''

cfg = configparser.ConfigParser(); cfg.read(os.path.expanduser('~/.ovh.conf'))
ep = cfg['default'].get('endpoint', 'ovh-eu'); s = cfg[ep]
base = {'ovh-eu': 'https://eu.api.ovh.com/1.0'}[ep]
url = base + path
ts = urllib.request.urlopen(base + '/auth/time').read().decode().strip()
sig = '$1$' + hashlib.sha1('+'.join([s['application_secret'], s['consumer_key'], method, url, body, ts]).encode()).hexdigest()
req = urllib.request.Request(url, data=body.encode() if body else None, method=method, headers={
    'X-Ovh-Application': s['application_key'], 'X-Ovh-Consumer': s['consumer_key'],
    'X-Ovh-Timestamp': ts, 'X-Ovh-Signature': sig, 'Content-Type': 'application/json'})
try:
    r = urllib.request.urlopen(req); status, raw = r.status, r.read()
except urllib.error.HTTPError as e:
    status, raw = e.code, e.read()
try:
    data = json.loads(raw) if raw else None
except ValueError:
    data = raw.decode(errors='replace')
if secret_out and isinstance(data, dict) and data.get('password'):
    fd = os.open(secret_out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f: f.write(data['password'])
    data['password'] = '<saved to %s>' % secret_out
print(status)
print(json.dumps(data, indent=1) if not isinstance(data, str) else data)
