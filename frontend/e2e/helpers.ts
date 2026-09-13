import { expect, type Page, type APIResponse } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

export const repoRoot = path.resolve(import.meta.dirname, '../..')

export function writeSanitizedEvidence(name: string, value: Record<string, unknown>): void {
  const runDir = process.env.FIM_E2E_RUN_DIR
  if (!runDir) return
  const resolved = path.resolve(runDir)
  mkdirSync(resolved, { recursive: true })
  writeFileSync(path.join(resolved, name), `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 })
}

interface LoginFixture { id: number; username: string; password: string }
const loginFixtures = new Map<number, LoginFixture>()

const createLoginFixtureScript = String.raw`
import json, secrets
from sqlmodel import Session
from app.core.database import engine
from app.core.security import hash_password
from app.core.config import settings
from app.modules.auth.models import User
import valkey
username = 'fim_e2e_' + secrets.token_hex(8)
password = secrets.token_urlsafe(24)
client = valkey.Valkey.from_url(settings.valkey_url, decode_responses=True)
# A fresh unique username should have no bucket. Delete only its exact prefix
# defensively before login; never scan/delete another user's keys.
keys = list(client.scan_iter(match=f'fim:rl:login:{username}:*'))
if keys: client.delete(*keys)
with Session(engine) as session:
    user = User(username=username, email=f'{username}@example.invalid',
        password_hash=hash_password(password), role='admin', is_active=True,
        must_change_password=False)
    session.add(user); session.commit(); session.refresh(user)
    print(json.dumps({'id': user.id, 'username': username, 'password': password}))
`

const cleanupLoginRateScript = String.raw`
import json, os, valkey
from app.core.config import settings
username = os.environ['FIM_E2E_USERNAME']
client = valkey.Valkey.from_url(settings.valkey_url, decode_responses=True)
keys = list(client.scan_iter(match=f'fim:rl:login:{username}:*'))
if len(keys) != 1:
    raise RuntimeError(f'expected exactly one isolated login bucket, got {len(keys)}')
client.delete(keys[0])
print(json.dumps({'deleted': 1, 'key_shape': 'fim:rl:login:<unique-user>:<observed-client-ip>'}))
`

const cleanupLoginFixtureScript = String.raw`
import os, valkey
from sqlmodel import Session, delete
from app.core.config import settings
from app.core.database import engine
from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
user_id = int(os.environ['FIM_E2E_USER_ID'])
username = os.environ['FIM_E2E_USERNAME']
client = valkey.Valkey.from_url(settings.valkey_url, decode_responses=True)
keys = list(client.scan_iter(match=f'fim:rl:login:{username}:*'))
if keys: client.delete(*keys)
with Session(engine) as session:
    session.exec(delete(AuditLog).where(AuditLog.user_id == user_id))
    session.exec(delete(User).where(User.id == user_id))
    session.commit()
`

function createLoginFixture(): LoginFixture {
  const fixture = JSON.parse(backendPython(createLoginFixtureScript, {})) as LoginFixture
  loginFixtures.set(fixture.id, fixture)
  return fixture
}

export function cleanupLoginFixtures(): void {
  for (const fixture of loginFixtures.values()) {
    backendPython(cleanupLoginFixtureScript, {
      FIM_E2E_USER_ID: String(fixture.id),
      FIM_E2E_USERNAME: fixture.username,
    })
    loginFixtures.delete(fixture.id)
  }
}

export async function login(page: Page): Promise<APIResponse> {
  const fixture = createLoginFixture()
  const loginResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/auth/login') && response.request().method() === 'POST',
  )
  await page.goto('/login')
  await page.getByLabel('Usuario').fill(fixture.username)
  await page.getByLabel('Contraseña').fill(fixture.password)
  await page.getByRole('button', { name: 'Ingresar' }).click()
  const response = await loginResponse
  expect(response.status()).toBe(200)
  const isolation = JSON.parse(backendPython(cleanupLoginRateScript, {
    FIM_E2E_USERNAME: fixture.username,
  })) as { deleted: number }
  expect(isolation.deleted).toBe(1)
  await expect(page).toHaveURL(/\/dashboard$/)
  return response
}

function backendPython(script: string, extraEnv: Record<string, string>): string {
  const composeArgs = ['compose', '--project-directory', repoRoot]
  if (process.env.FIM_E2E_COMPOSE_PROJECT) {
    composeArgs.push('-p', process.env.FIM_E2E_COMPOSE_PROJECT)
  }
  if (process.env.FIM_E2E_COMPOSE_FILE) {
    composeArgs.push('-f', path.resolve(process.env.FIM_E2E_COMPOSE_FILE))
  }
  return execFileSync(
    'docker',
    [...composeArgs, 'exec', '-T', ...Object.entries(extraEnv).flatMap(([key, value]) => ['-e', `${key}=${value}`]), 'backend', 'python', '-c', script],
    { cwd: repoRoot, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] },
  ).trim()
}

function composeService(action: 'stop' | 'start', service: string): void {
  const composeArgs = ['compose', '--project-directory', repoRoot]
  if (process.env.FIM_E2E_COMPOSE_PROJECT) {
    composeArgs.push('-p', process.env.FIM_E2E_COMPOSE_PROJECT)
  }
  if (process.env.FIM_E2E_COMPOSE_FILE) {
    composeArgs.push('-f', path.resolve(process.env.FIM_E2E_COMPOSE_FILE))
  }
  execFileSync('docker', [...composeArgs, action, service], {
    cwd: repoRoot,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  })
}

export function stopBackendService(): void {
  composeService('stop', 'backend')
}

export function startBackendService(): void {
  composeService('start', 'backend')
}

export function stopSseProxyService(): void {
  composeService('stop', 'sse-proxy')
}

export function startSseProxyService(): void {
  composeService('start', 'sse-proxy')
}

const externalChannelPreflightScript = String.raw`
import json
from app.core.config import settings
configured = [name for name, value in {
  'N8N_WEBHOOK_URL': settings.n8n_webhook_url,
  'SMTP_HOST': settings.smtp_host,
  'WEBHOOK_FALLBACK_URL': settings.webhook_fallback_url,
}.items() if value]
print(json.dumps({'safe': not configured, 'configured': configured}))
`

export function assertExternalNotificationChannelsEmpty(): void {
  const result = JSON.parse(backendPython(externalChannelPreflightScript, {})) as {
    safe: boolean
    configured: string[]
  }
  if (!result.safe) {
    throw new Error(`BLOCKED: external notification channels configured: ${result.configured.join(', ')}`)
  }
}

const realtimeFixtureScript = String.raw`
import json, os, secrets, uuid
from sqlmodel import Session
from app.core.database import engine
from app.modules.agents.models import Agent, AgentStatus
from app.modules.rules.models import Rule, RuleAction, RuleSeverity

prefix = os.environ['FIM_E2E_PREFIX']
agent_id = 'fim-e2e-agent-' + uuid.uuid4().hex
secret = secrets.token_bytes(32)
pattern = f'/fim-e2e/{prefix}-*'
with Session(engine) as session:
    agent = Agent(agent_id=agent_id, status=AgentStatus.online,
        shared_secret_hex=secret.hex(), watch_paths=[])
    rule = Rule(pattern=pattern, severity=RuleSeverity.high, action=RuleAction.manual_review)
    session.add(agent); session.add(rule); session.commit(); session.refresh(rule)
    print(json.dumps({'agent_id': agent_id, 'secret_hex': secret.hex(),
      'rule_id': rule.id, 'pattern': pattern}))
`

const publishRealtimeEventScript = String.raw`
import hashlib, hmac, json, os, uuid
from datetime import datetime, timezone
import valkey
from app.core.config import settings
from app.core.streams import canonical_json

now = datetime.now(timezone.utc).isoformat()
payload = {
  'schema_version': 1,
  'event_id': str(uuid.uuid4()),
  'agent_id': os.environ['FIM_E2E_AGENT_ID'],
  'event_type': 'file_modified',
  'path': os.environ['FIM_E2E_PATH'],
  'hash_detected': hashlib.sha256(os.urandom(32)).hexdigest(),
  'detected_at': now,
  'sent_at': now,
  'process_pid': 4242,
  'process_uid': 1000,
  'process_exe': '/usr/bin/fim-e2e',
}
secret = bytes.fromhex(os.environ['FIM_E2E_SECRET_HEX'])
payload['signature'] = hmac.new(secret, canonical_json(payload).encode(), hashlib.sha256).hexdigest()
client = valkey.Valkey.from_url(settings.valkey_url, decode_responses=True)
message_id = client.xadd('events', {'data': json.dumps(payload, sort_keys=True, separators=(',', ':'))})
print(json.dumps({'event_uuid': payload['event_id'], 'message_id': message_id, 'path': payload['path']}))
`

const probeRealtimeEventScript = String.raw`
import json, os
from sqlmodel import Session, select
from app.core.database import engine
from app.modules.alerts.models import Alert
from app.modules.events.models import Event

event_uuid = os.environ['FIM_E2E_EVENT_UUID']
with Session(engine) as session:
    event = session.exec(select(Event).where(Event.event_id == event_uuid)).first()
    alert = session.exec(select(Alert).where(Alert.event_id == event.id)).first() if event else None
    print(json.dumps({'event_id': event.id if event else None,
      'alert_id': alert.id if alert else None,
      'severity': alert.severity.value if alert else None,
      'channel': alert.channel.value if alert and alert.channel else None,
      'delivered': bool(alert and alert.delivered_at)}))
`

const cleanupRealtimeFixtureScript = String.raw`
import json, os
import valkey
from sqlmodel import Session, delete, select
from app.core.config import settings
from app.core.database import engine
from app.modules.agents.models import Agent
from app.modules.alerts.models import Alert
from app.modules.events.models import Event, RejectedEventAudit
from app.modules.rules.models import Rule

agent_id = os.environ['FIM_E2E_AGENT_ID']
rule_id = int(os.environ['FIM_E2E_RULE_ID'])
event_uuids = [v for v in os.environ.get('FIM_E2E_EVENT_UUIDS', '').split(',') if v]
message_ids = [v for v in os.environ.get('FIM_E2E_MESSAGE_IDS', '').split(',') if v]
client = valkey.Valkey.from_url(settings.valkey_url, decode_responses=True)
ack_message_ids = []
for message_id, fields in client.xrange('event_ack'):
    try:
        payload = json.loads(fields.get('data', '{}'))
    except (TypeError, json.JSONDecodeError):
        continue
    if payload.get('event_id') in event_uuids:
        ack_message_ids.append(message_id)
if message_ids: client.xdel('events', *message_ids)
if ack_message_ids: client.xdel('event_ack', *ack_message_ids)
with Session(engine) as session:
    event_ids = list(session.exec(select(Event.id).where(Event.event_id.in_(event_uuids))).all()) if event_uuids else []
    if event_ids: session.exec(delete(Alert).where(Alert.event_id.in_(event_ids)))
    session.exec(delete(RejectedEventAudit).where(RejectedEventAudit.agent_id == agent_id))
    if event_uuids: session.exec(delete(Event).where(Event.event_id.in_(event_uuids)))
    session.exec(delete(Rule).where(Rule.id == rule_id))
    session.exec(delete(Agent).where(Agent.agent_id == agent_id))
    session.commit()
print(json.dumps({'event_messages_deleted': len(message_ids),
  'ack_messages_deleted': len(ack_message_ids), 'fixture_rows_deleted': True}))
`

export interface RealtimeFixture {
  agent_id: string
  secret_hex: string
  rule_id: number
  pattern: string
  eventUuids: string[]
  messageIds: string[]
}

export interface PublishedRealtimeEvent { event_uuid: string; message_id: string; path: string }

export function createRealtimeFixture(prefix: string): RealtimeFixture {
  return {
    ...(JSON.parse(backendPython(realtimeFixtureScript, { FIM_E2E_PREFIX: prefix })) as Omit<RealtimeFixture, 'eventUuids' | 'messageIds'>),
    eventUuids: [],
    messageIds: [],
  }
}

export function publishRealtimeEvent(fixture: RealtimeFixture, pathValue: string): PublishedRealtimeEvent {
  const published = JSON.parse(backendPython(publishRealtimeEventScript, {
    FIM_E2E_AGENT_ID: fixture.agent_id,
    FIM_E2E_SECRET_HEX: fixture.secret_hex,
    FIM_E2E_PATH: pathValue,
  })) as PublishedRealtimeEvent
  fixture.eventUuids.push(published.event_uuid)
  fixture.messageIds.push(published.message_id)
  return published
}

export function probeRealtimeEvent(eventUuid: string): Record<string, unknown> {
  return JSON.parse(backendPython(probeRealtimeEventScript, { FIM_E2E_EVENT_UUID: eventUuid })) as Record<string, unknown>
}

export function cleanupRealtimeFixture(fixture: RealtimeFixture): Record<string, unknown> {
  return JSON.parse(backendPython(cleanupRealtimeFixtureScript, {
    FIM_E2E_AGENT_ID: fixture.agent_id,
    FIM_E2E_RULE_ID: String(fixture.rule_id),
    FIM_E2E_EVENT_UUIDS: fixture.eventUuids.join(','),
    FIM_E2E_MESSAGE_IDS: fixture.messageIds.join(','),
  })) as Record<string, unknown>
}

const supersededFixtureScript = String.raw`
import json, os, uuid
from datetime import datetime, timezone
from sqlmodel import Session
from app.core.database import engine
from app.modules.agents.models import Agent, AgentStatus
from app.modules.events.models import Event, EventStatus

agent_id = 'fim-e2e-agent-' + uuid.uuid4().hex
path = '/fim-e2e/' + os.environ['FIM_E2E_PREFIX'] + '.txt'
now = datetime.now(timezone.utc)
with Session(engine) as session:
    session.add(Agent(agent_id=agent_id, status=AgentStatus.offline, watch_paths=[]))
    grandparent = Event(event_id=str(uuid.uuid4()), agent_id=agent_id, event_type='file_modified',
      path=path, hash_detected='a' * 64, status=EventStatus.superseded,
      severity='low', detected_at=now, received_at=now)
    session.add(grandparent); session.flush()
    parent = Event(event_id=str(uuid.uuid4()), agent_id=agent_id, event_type='file_modified',
      path=path, hash_detected='b' * 64, status=EventStatus.superseded,
      severity='low', parent_event_id=grandparent.id, detected_at=now, received_at=now)
    session.add(parent); session.flush()
    child = Event(event_id=str(uuid.uuid4()), agent_id=agent_id, event_type='file_modified',
      path=path, hash_detected='c' * 64, status=EventStatus.pending,
      severity='low', parent_event_id=parent.id, detected_at=now, received_at=now)
    session.add(child); session.commit(); session.refresh(child)
    print(json.dumps({'agent_id': agent_id, 'path': path,
      'parent_id': grandparent.id, 'superseded_id': parent.id, 'child_id': child.id}))
`

const cleanupSupersededFixtureScript = String.raw`
import os
from sqlmodel import Session, delete
from app.core.database import engine
from app.modules.agents.models import Agent
from app.modules.events.models import Event
ids = [int(v) for v in os.environ['FIM_E2E_EVENT_IDS'].split(',')]
with Session(engine) as session:
    session.exec(delete(Event).where(Event.id.in_(ids)))
    session.exec(delete(Agent).where(Agent.agent_id == os.environ['FIM_E2E_AGENT_ID']))
    session.commit()
`

export interface SupersededFixture { agent_id: string; path: string; parent_id: number; superseded_id: number; child_id: number }

export function createSupersededFixture(prefix: string): SupersededFixture {
  return JSON.parse(backendPython(supersededFixtureScript, { FIM_E2E_PREFIX: prefix })) as SupersededFixture
}

export function cleanupSupersededFixture(fixture: SupersededFixture): void {
  backendPython(cleanupSupersededFixtureScript, {
    FIM_E2E_AGENT_ID: fixture.agent_id,
    FIM_E2E_EVENT_IDS: `${fixture.child_id},${fixture.superseded_id},${fixture.parent_id}`,
  })
}

const fixtureScript = String.raw`
import json, os, uuid
from datetime import datetime, timezone
from sqlmodel import Session, select
from app.core.database import engine
from app.modules.agents.models import Agent, AgentStatus, BaselineEntry, BaselineStatus
from app.modules.events.models import Event, EventStatus
from app.modules.rules.models import RulesetVersion

prefix = os.environ['FIM_E2E_PREFIX']
with Session(engine) as session:
    agent = session.exec(select(Agent).where(Agent.status == AgentStatus.online)).first()
    if agent is None or not agent.shared_secret_hex:
        raise RuntimeError('No online enrolled agent is available')
    rv = session.exec(select(RulesetVersion).order_by(RulesetVersion.id.desc())).first()
    version = rv.version if rv else 0
    ids, paths = [], []
    now = datetime.now(timezone.utc)
    for index in range(1, 13):
        path = f'/watch/{prefix}-{index:02d}.txt'
        event = Event(event_id=str(uuid.uuid4()), agent_id=agent.agent_id,
            event_type='file_modified', path=path, hash_detected=('a' * 64),
            status=EventStatus.pending, severity='low', version=0,
            detected_at=now, received_at=now)
        session.add(event)
        session.flush()
        session.add(BaselineEntry(path=path, agent_id=agent.agent_id, hash=None,
            status=BaselineStatus.absent, ruleset_version=version))
        ids.append(event.id); paths.append(path)
    session.commit()
    print(json.dumps({'ids': ids, 'paths': paths, 'agent_id': agent.agent_id}))
`

const bumpScript = String.raw`
import os
from sqlmodel import Session, select
from app.core.database import engine
from app.modules.events.models import Event
with Session(engine) as session:
    event = session.exec(select(Event).where(Event.id == int(os.environ['FIM_E2E_EVENT_ID']))).one()
    event.version += 1
    session.add(event); session.commit()
`

const probeScript = String.raw`
import json, os
from sqlmodel import Session, select
from app.core.database import engine
from app.modules.audit.models import AuditLog
from app.modules.events.models import Event
from app.modules.rules.models import PublishedCommand
ids = [int(v) for v in os.environ['FIM_E2E_IDS'].split(',')]
with Session(engine) as session:
    events = session.exec(select(Event).where(Event.id.in_(ids))).all()
    audits = session.exec(select(AuditLog).where(AuditLog.target_type == 'event', AuditLog.target_id.in_(ids))).all()
    commands = session.exec(select(PublishedCommand).where(PublishedCommand.event_id.in_(ids))).all()
    print(json.dumps({'pending': sum(str(e.status.value) == 'pending' for e in events),
      'rejected': sum(str(e.status.value) == 'rejected' for e in events),
      'audit_count': len(audits), 'command_count': len(commands)}))
`

const cleanupScript = String.raw`
import os
from sqlmodel import Session, delete
from app.core.database import engine
from app.modules.agents.models import BaselineEntry
from app.modules.audit.models import AuditLog
from app.modules.events.models import Event
from app.modules.rules.models import PublishedCommand
ids = [int(v) for v in os.environ['FIM_E2E_IDS'].split(',')]
paths = os.environ['FIM_E2E_PATHS'].split('\n')
with Session(engine) as session:
    session.exec(delete(PublishedCommand).where(PublishedCommand.event_id.in_(ids)))
    session.exec(delete(AuditLog).where(AuditLog.target_type == 'event', AuditLog.target_id.in_(ids)))
    session.exec(delete(BaselineEntry).where(BaselineEntry.path.in_(paths)))
    session.exec(delete(Event).where(Event.id.in_(ids)))
    session.commit()
`

export interface BulkFixture { ids: number[]; paths: string[]; agent_id: string }

export function createBulkFixture(prefix: string): BulkFixture {
  return JSON.parse(backendPython(fixtureScript, { FIM_E2E_PREFIX: prefix })) as BulkFixture
}

export function bumpEventVersion(eventId: number): void {
  backendPython(bumpScript, { FIM_E2E_EVENT_ID: String(eventId) })
}

export function probeBulkFixture(fixture: BulkFixture): Record<string, number> {
  return JSON.parse(backendPython(probeScript, { FIM_E2E_IDS: fixture.ids.join(',') })) as Record<string, number>
}

export function cleanupBulkFixture(fixture: BulkFixture): void {
  backendPython(cleanupScript, {
    FIM_E2E_IDS: fixture.ids.join(','),
    FIM_E2E_PATHS: fixture.paths.join('\n'),
  })
}
