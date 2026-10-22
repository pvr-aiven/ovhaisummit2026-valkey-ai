"""Faux Valkey en mémoire pour les tests (sous-ensemble des commandes utilisées par la démo)."""
import re
import time

import numpy as np


class FakeValkey:
    def __init__(self):
        self.h, self.kv, self.streams, self.index = {}, {}, {}, None
        self.indexes = {}
        self._seq = 0

    # --- API valkey-py utilisée
    def ping(self):
        return True

    def info(self, section=None):
        return {"valkey_version": "9.1.2"}

    def pipeline(self, transaction=False):
        return self

    def execute(self):
        return []

    def hset(self, key, mapping):
        self.h.setdefault(key, {}).update({k.encode(): v if isinstance(v, bytes) else str(v).encode() for k, v in mapping.items()})

    def hgetall(self, key):
        return dict(self.h.get(key, {}))

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, value, ex=None):
        self.kv[key] = value.encode() if isinstance(value, str) else value

    def expire(self, key, ttl):
        return True

    def hincrby(self, key, field, n):
        h = self.h.setdefault(key, {})
        h[field.encode()] = str(int(float(h.get(field.encode(), b"0"))) + int(n)).encode()

    def hincrbyfloat(self, key, field, x):
        h = self.h.setdefault(key, {})
        h[field.encode()] = repr(float(h.get(field.encode(), b"0")) + float(x)).encode()

    def delete(self, key):
        self.h.pop(key, None)
        self.streams.pop(key, None)
        self.kv.pop(key, None)

    def scan_iter(self, match="*", count=None):
        pre = match.rstrip("*")
        return iter([k for k in list(self.h) if k.startswith(pre)])

    # --- commandes brutes
    def _match(self, d, filt):
        for fld, vals in re.findall(r"@(\w+):\{([^}]*)\}", filt):
            if d.get(fld.encode(), b"").decode() not in [v.strip() for v in vals.split("|")]:
                return False
        for fld, word in re.findall(r"@(\w+):(\w+)(?![\w{])", filt):
            if word.lower() not in d.get(fld.encode(), b"").decode().lower():
                return False
        return True

    def execute_command(self, *args):
        cmd = args[0]
        if cmd == "FT.CREATE":
            self.indexes[args[1]] = args[args.index("PREFIX") + 2]
            return b"OK"
        if cmd == "FT.INFO":
            if args[1] not in self.indexes:
                raise Exception("Unknown index name")
            pre = self.indexes[args[1]]
            return [b"num_docs", str(sum(1 for k in self.h if k.startswith(pre))).encode()]
        if cmd == "FT.DROPINDEX":
            self.indexes.pop(args[1], None)
            return b"OK"
        if cmd == "FT.SEARCH":
            query = args[2]
            m = re.match(r"^(?:\((.*)\)|\*)=>\[KNN (\d+) @embedding \$vec AS score\]$", query)
            filt = (m.group(1) or "") if m else query
            pre = self.indexes.get(args[1], "")
            docs = [(k, d) for k, d in self.h.items() if k.startswith(pre) and b"embedding" in d and self._match(d, filt)]
            if m:
                q = np.frombuffer(args[args.index("PARAMS") + 3], dtype="<f4")
                scored = sorted(((k, d, 1 - float(np.dot(q, np.frombuffer(d[b"embedding"], dtype="<f4")))) for k, d in docs),
                                key=lambda x: x[2])[: int(m.group(2))]
            else:
                scored = [(k, d, None) for k, d in docs]
            if "NOCONTENT" in args:
                return [len(scored)] + [k.encode() for k, _, _ in scored]
            r = args.index("RETURN")
            ret = args[r + 2: r + 2 + int(args[r + 1])]
            out = [len(scored)]
            for k, d, dist in scored[: int(args[args.index("LIMIT") + 2])]:
                fields = []
                for f in ret:
                    if f == "score" and dist is not None:
                        fields += [b"score", str(dist).encode()]
                    elif f.encode() in d:
                        fields += [f.encode(), d[f.encode()]]
                out += [k.encode(), fields]
            return out
        if cmd == "XADD":
            self._seq += 1
            eid = f"{int(time.time() * 1000)}-{self._seq}".encode()
            flat = [a.encode() if isinstance(a, str) else a for a in args[3:]]
            self.streams.setdefault(args[1], []).append((eid, flat))
            return eid
        if cmd == "XREVRANGE":
            n = int(args[args.index("COUNT") + 1]) if "COUNT" in args else 10**9
            return list(reversed(self.streams.get(args[1], [])))[:n]
        if cmd == "XLEN":
            return len(self.streams.get(args[1], []))
        if cmd == "EXPIRE":
            return 1
        raise NotImplementedError(cmd)
