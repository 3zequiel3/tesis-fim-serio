#!/usr/bin/env python3
import json,re,subprocess,sys,xml.etree.ElementTree as ET
from pathlib import Path
R=Path(__file__).resolve().parent; fail=[]
for p in R.rglob('*.xml'):
 try: ET.parse(p)
 except Exception as x: fail.append(f'XML {p.relative_to(R)}: {x}')
d=json.loads((R/'results.json').read_text())
expect={'agent':{'tests':508,'failures':0,'errors':0,'skipped':1},'backend':{'tests':599,'failures':0,'errors':0,'skipped':0},'frontend':{'tests':128,'failures':0,'errors':0,'skipped':0}}
for c,x in expect.items():
 if d[c]['junit']!=x:fail.append(f'{c} denominator mismatch')
if d['agent']['coverage']['lines_covered']!=2638 or d['agent']['coverage']['lines_valid']!=3342:fail.append('agent coverage mismatch')
if d['backend']['coverage']['lines_covered']!=2737 or d['backend']['coverage']['lines_valid']!=3018:fail.append('backend coverage mismatch')
f=d['frontend']['coverage']
if f['lines']!={'total':3441,'covered':1995,'skipped':0,'pct':57.97}:fail.append('frontend line coverage mismatch')
if f['functions']['covered']!=105 or f['branches']['covered']!=396:fail.append('frontend function/branch coverage mismatch')
if d['openspec_integrity']!={'exit_code':0,'specs':44,'requirements':249,'ok':True}:fail.append('OpenSpec mismatch')
for c in ('agent','backend'):
 if d[c]['exit_code']!=0:fail.append(f'{c} exit')
for k in ('test_exit_code','typecheck_exit_code','build_exit_code'):
 if d['frontend'][k]!=0:fail.append(f'frontend {k}')
for k in ('e2e_us02_us20_us31','e2e_us03_us16_us17_us25'):
 if d[k]['exit_code']!=0:fail.append(f'{k} exit')
patterns={'private_key':re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),'jwt':re.compile(rb'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'),'bearer':re.compile(rb'Authorization:\s*Bearer\s+(?!\[REDACTED\])[A-Za-z0-9._~-]{12,}',re.I),'db_password':re.compile(rb'postgresql(?:\+psycopg)?://[^:\s/]+:(?!\[REDACTED\]|\[TEST_PASSWORD\])[^@\s]+@',re.I),'private_home':re.compile(rb'/home/ezequiel(?:/|\b)'),'hostname':re.compile(rb'Eze-Linux')}
for p in R.rglob('*'):
 if not p.is_file() or p.name in ('SHA256SUMS','verify-evidence.py'):continue
 b=p.read_bytes()
 for n,rx in patterns.items():
  if rx.search(b):fail.append(f'{n}: {p.relative_to(R)}')
for x in ('e2e-us02-us20-us31','e2e-us02-us20-us31-attempt1-main-stack-changed','e2e-us03-us16-us17-us25'):
 cp=subprocess.run(['sha256sum','-c','SHA256SUMS'],cwd=R/x,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT)
 if cp.returncode:fail.append(f'{x} checksum')
for x in ('e2e-us02-us20-us31','e2e-us02-us20-us31-attempt1-main-stack-changed','e2e-us03-us16-us17-us25'):
 q=json.loads((R/x/'teardown-result.json').read_text())
 if any(q[k]!=0 for k in ('lab_containers_remaining','lab_volumes_remaining','lab_networks_remaining')):fail.append(f'{x} residual resources')
if fail:
 print('FAIL'); print('\n'.join(fail));sys.exit(1)
print('PASS: suites, XML, coverage, OpenSpec, privacy, nested checksums, and zero residual lab resources')
