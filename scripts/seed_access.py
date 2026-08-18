"""Seed config/access, without which the security rules fail closed and deny everything.

`accessOk()` in firestore.rules does get(config/access); a missing doc makes that get() fail and
every trip/refine create is denied ("Missing or insufficient permissions"). See spec/access.md.
The doc is locked from all clients, so it is written with the Admin path (ADC), which bypasses rules.

Usage: python seed_access.py <email> [more emails...]      # allowlist mode (recommended)
       python seed_access.py --open                        # any verified Google account
"""

import sys

from google.cloud import firestore

args = sys.argv[1:]
if not args:
    sys.exit(__doc__)

if args[0] == "--open":
    # 'open' lets ANY verified Google account create jobs, and a job is paid agent work.
    payload = {"mode": "open", "allowedEmails": []}
else:
    payload = {"mode": "allowlist", "allowedEmails": sorted({a.strip().lower() for a in args})}

db = firestore.Client(project="tripper-af0fc")
db.collection("config").document("access").set(payload)
print(f"seeded config/access = {payload}")
