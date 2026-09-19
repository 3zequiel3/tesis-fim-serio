#!/usr/bin/env python3
from pathlib import Path
import re,sys,json
base=Path(sys.argv[1]); raw=base/'raw'; out=base/'sanitized';out.mkdir(exist_ok=True)
ansi=re.compile(r'\x1b\[[0-9;]*m'); jwt=re.compile(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')
replacements=[(str(Path.cwd()),'[REPO]'),(re.escape(str(base.resolve())), '[EVIDENCE]')]
for p in sorted(raw.glob('*')):
 if not p.is_file(): continue
 try:s=p.read_text()
 except UnicodeDecodeError:continue
 s=ansi.sub('',s);s=jwt.sub('[REDACTED-JWT]',s);s=re.sub(r'/tmp/fim-(?:latency-lab|experiments)-[^\s"\']+','[TEMP]',s);s=s.replace(str(base.resolve()),'[EVIDENCE]').replace(str(Path.cwd()),'[REPO]')
 (out/p.name).write_text(s)
# privacy scan over the retained package; hashes/event ids are not credentials.
patterns={'private_key':r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----','jwt':r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}','aws_access_key':r'AKIA[0-9A-Z]{16}','password_assignment':r'(?i)(?:password|secret)\s*=\s*[^\s$<{][^\s]*'}
findings={k:[] for k in patterns}
for p in sorted(base.rglob('*')):
 if not p.is_file() or p.name in {'SHA256SUMS','privacy-scan.json','sanitize_logs.py'}:continue
 try:s=p.read_text(errors='strict')
 except (UnicodeDecodeError,PermissionError):continue
 for k,pat in patterns.items():
  if re.search(pat,s):findings[k].append(str(p.relative_to(base)))
controlled=[]
for rel in list(findings['password_assignment']):
 q=base/rel
 if q.name=='run_profile.py' and 'SECRET = bytes.fromhex("4f" * 32)' in q.read_text():
  findings['password_assignment'].remove(rel);controlled.append(rel)
res={'patterns':{k:v for k,v in findings.items()},'controlled_synthetic_secret_literal_copies':controlled,'passed':not any(findings.values()),'note':'Long hexadecimal hashes and UUID event identifiers are expected evidence. The fixed 0x4f laboratory HMAC key in copied Run 4 harnesses is synthetic and never leaves localhost.'}
(base/'metadata/privacy-scan.json').write_text(json.dumps(res,indent=2,sort_keys=True)+'\n');print(json.dumps(res,indent=2,sort_keys=True))
raise SystemExit(0 if res['passed'] else 1)
