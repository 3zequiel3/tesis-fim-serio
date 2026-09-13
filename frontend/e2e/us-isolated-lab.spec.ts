import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import path from 'node:path'

const repoRoot = path.resolve(import.meta.dirname, '../..')
const composeFile = path.join(repoRoot, 'docker-compose.acceptance-lab.yml')
const project = required('FIM_LAB_PROJECT')
const adminUser = required('FIM_LAB_ADMIN_USERNAME')
const adminPassword = required('FIM_LAB_ADMIN_PASSWORD_FINAL')
const us17File = required('FIM_LAB_US17_FILE')
const us25File = required('FIM_LAB_US25_FILE')

function required(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`${name} is required`)
  return value
}

function composePython(script: string, env: Record<string, string> = {}): string {
  return execFileSync('docker', [
    'compose', '-p', project, '-f', composeFile, 'exec', '-T',
    ...Object.entries(env).flatMap(([key, value]) => ['-e', `${key}=${value}`]),
    'backend', 'python', '-c', script,
  ], { cwd: repoRoot, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim()
}

function agentPython(script: string, env: Record<string, string> = {}): string {
  return execFileSync('docker', [
    'compose', '-p', project, '-f', composeFile, 'exec', '-T',
    ...Object.entries(env).flatMap(([key, value]) => ['-e', `${key}=${value}`]),
    'agent', 'python', '-c', script,
  ], { cwd: repoRoot, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim()
}

async function login(page: import('@playwright/test').Page): Promise<string> {
  composePython("import os,valkey; from sqlmodel import Session,select; from app.core.config import settings; from app.core.database import engine; from app.modules.auth.models import User; c=valkey.Valkey.from_url(settings.valkey_url); ks=list(c.scan_iter(match='fim:rl:login:'+os.environ['USERNAME']+':*')); c.delete(*ks) if ks else None; s=Session(engine); u=s.exec(select(User).where(User.username==os.environ['USERNAME'])).first(); c.delete('fim:rl:api:'+str(u.id)) if u else None; s.close()", { USERNAME: adminUser })
  await page.goto('/login')
  await page.getByLabel('Usuario').fill(adminUser)
  await page.getByLabel('Contraseña').fill(adminPassword)
  const response = page.waitForResponse((item) => item.url().endsWith('/api/auth/login'))
  await page.getByRole('button', { name: 'Ingresar' }).click()
  const loginResponse = await response
  expect(loginResponse.status()).toBe(200)
  await expect(page).toHaveURL(/\/dashboard/)
  return ((await loginResponse.json()) as { access_token: string }).access_token
}

test('US-03 uses the canonical refresh path and revokes the rotated refresh on logout', async ({ page }, testInfo) => {
  const access = await login(page)
  const before = (await page.context().cookies()).find((cookie) => cookie.name === 'refresh_token')
  expect(before).toMatchObject({ httpOnly: true, sameSite: 'Strict', path: '/auth/refresh' })

  const refreshRequest = page.waitForRequest((request) =>
    request.method() === 'POST' && new URL(request.url()).pathname === '/auth/refresh'
  )
  const refreshResponse = page.waitForResponse((response) =>
    response.request().method() === 'POST' && new URL(response.url()).pathname === '/auth/refresh'
  )
  await page.evaluate(async () => {
    const response = await fetch('/auth/refresh', { method: 'POST', credentials: 'include' })
    if (!response.ok) throw new Error(`refresh failed: ${response.status}`)
  })
  expect(new URL((await refreshRequest).url()).pathname).toBe('/auth/refresh')
  const refresh = await refreshResponse
  expect(refresh.status()).toBe(200)
  const rotatedAccess = ((await refresh.json()) as { access_token: string }).access_token
  const after = (await page.context().cookies()).find((cookie) => cookie.name === 'refresh_token')
  expect(after).toMatchObject({ httpOnly: true, sameSite: 'Strict', path: '/auth/refresh' })
  expect(createHash('sha256').update(after!.value).digest('hex')).not.toBe(
    createHash('sha256').update(before!.value).digest('hex')
  )

  const logout = await page.request.post('/api/auth/logout', {
    headers: { Authorization: `Bearer ${rotatedAccess}` },
  })
  expect(logout.status()).toBe(200)
  const reuse = await page.request.post('/auth/refresh', {
    headers: { Cookie: `refresh_token=${after!.value}` },
  })
  expect(reuse.status()).toBe(401)
  const predecessorReuse = await page.request.post('/auth/refresh', {
    headers: { Cookie: `refresh_token=${before!.value}` },
  })
  expect(predecessorReuse.status()).toBe(401)
  expect((await page.context().cookies()).filter((cookie) => cookie.name === 'refresh_token')).toHaveLength(0)
  await testInfo.attach('us03-cookie-wire-sanitized.json', {
    body: JSON.stringify({ path: '/auth/refresh', httpOnly: true, sameSite: 'Strict', rotated: true, logout: 200, reuse: 401, initial_access_present: access.length > 0 }, null, 2),
    contentType: 'application/json',
  })
})

const probeRule = String.raw`
import json, os
from sqlmodel import Session, select
from app.core.database import engine
from app.modules.agents.models import Agent
from app.modules.audit.models import AuditLog
from app.modules.rules.models import Rule, RulesetVersion, PublishedCommand
from app.modules.agents.models import Agent
from app.core.streams import verify_payload
pattern = os.environ['PATTERN']
with Session(engine) as s:
    rule = s.exec(select(Rule).where(Rule.pattern == pattern)).first()
    version = s.exec(select(RulesetVersion)).first()
    agent = s.get(Agent, os.environ['AGENT_ID'])
    audits = s.exec(select(AuditLog).where(AuditLog.target_type == 'rule')).all()
    commands = s.exec(select(PublishedCommand).where(PublishedCommand.command_type == 'rule_sync').order_by(PublishedCommand.id)).all()
    print(json.dumps({'rule_id': rule.id if rule else None, 'severity': rule.severity.value if rule else None,
      'action': rule.action.value if rule else None, 'version': version.version if version else 0,
      'agent_version': agent.ruleset_version_applied if agent else -1,
      'audit_actions': [a.action for a in audits],
      'commands': [{'status': c.status, 'version': c.ruleset_version, 'ack_status': c.ack_status,
        'signature_valid': verify_payload(bytes.fromhex(agent.shared_secret_hex), json.loads(c.payload)),
        'schema_version': json.loads(c.payload).get('schema_version')} for c in commands]}))
`

const probeEvent = String.raw`
import json, os
from sqlmodel import Session, select
from app.core.database import engine
from app.modules.events.models import Event
from app.modules.audit.models import AuditLog
from app.modules.rules.models import PublishedCommand
from app.modules.agents.models import Agent
from app.core.streams import verify_payload
with Session(engine) as s:
    events = s.exec(select(Event).where(Event.path == os.environ['PROBE_PATH']).order_by(Event.id)).all()
    event = events[-1] if events else None
    commands = s.exec(select(PublishedCommand).where(PublishedCommand.event_id == (event.id if event else -1))).all()
    audits = s.exec(select(AuditLog).where(AuditLog.target_type == 'event', AuditLog.target_id == (event.id if event else -1))).all()
    agent = s.get(Agent, event.agent_id) if event else None
    print(json.dumps({'event_id': event.id if event else None, 'event_uuid': event.event_id if event else None,
      'status': event.status.value if event else None, 'version': event.version if event else None,
      'hash_detected': event.hash_detected if event else None,
      'audit_actions': [a.action for a in audits],
      'commands': [{'type': c.command_type, 'status': c.status, 'ack_status': c.ack_status,
        'ruleset_version': c.ruleset_version,
        'signature_valid': verify_payload(bytes.fromhex(agent.shared_secret_hex), json.loads(c.payload)),
        'schema_version': json.loads(c.payload).get('schema_version')} for c in commands]}))
`

const probeAgent = String.raw`
import json, os
from pathlib import Path
from agent.baseline import BaselineEngine, load_master_secret
from agent.config import load_config
from agent.state import load_state
cfg = load_config('/etc/fim-agent/config.yaml')
state = load_state()
result = {'ruleset_version': state.ruleset_version,
  'rules': [{'pattern': r.get('pattern'), 'action': r.get('action')} for r in state.rules]}
if os.environ.get('PROBE_PATH'):
    engine = BaselineEngine(cfg, load_master_secret(cfg.storage.secrets_dir))
    entry = engine.read_entry(os.environ['PROBE_PATH'])
    result['baseline'] = {'status': entry.status, 'hash': entry.hash,
      'approved_event_id': entry.approved_event_id} if entry else None
print(json.dumps(result))
`

test('US-16 and US-17 edit/delete a rule and synchronize the real isolated agent', async ({ page }, testInfo) => {
  const agentId = required('FIM_LAB_AGENT_ID')
  let deleteRequests = 0
  page.on('request', (request) => {
    if (request.method() === 'DELETE' && request.url().includes('/api/rules/')) deleteRequests += 1
  })
  const initialPattern = '/watch/us16-initial-*'
  const editedPattern = '/watch/us16-final-*'
  await login(page)
  await page.goto('/rules')
  await page.getByRole('button', { name: /Nueva regla|Crear la primera regla/ }).click()
  let dialog = page.getByRole('dialog')
  await dialog.getByLabel(/^Pattern/).fill(initialPattern)
  await dialog.getByLabel('Severidad').selectOption('medium')
  await dialog.getByLabel('Acción').selectOption('manual_review')
  await page.getByRole('button', { name: 'Crear regla' }).click()
  await expect(page.getByText(initialPattern)).toBeVisible()
  const createdProbe = JSON.parse(composePython(probeRule, { PATTERN: initialPattern, AGENT_ID: agentId }))

  const row = page.getByRole('row').filter({ hasText: initialPattern })
  await row.getByRole('button', { name: 'Editar' }).click()
  dialog = page.getByRole('dialog')
  await expect(dialog.getByLabel(/^Pattern/)).toHaveValue(initialPattern)
  await expect(dialog.getByLabel('Severidad')).toHaveValue('medium')
  await expect(dialog.getByLabel('Acción')).toHaveValue('manual_review')
  await dialog.getByLabel(/^Pattern/).fill(editedPattern)
  await dialog.getByLabel('Severidad').selectOption('high')
  await dialog.getByLabel('Acción').selectOption('alert_only')
  const put = page.waitForResponse((r) => r.url().includes('/api/rules/') && r.request().method() === 'PUT')
  await page.getByRole('button', { name: 'Guardar cambios' }).click()
  expect((await put).status()).toBe(200)
  await expect(page.getByText(editedPattern)).toBeVisible()

  await expect.poll(() => {
    const p = JSON.parse(composePython(probeRule, { PATTERN: editedPattern, AGENT_ID: agentId }))
    const a = JSON.parse(agentPython(probeAgent))
    return p.commands.at(-1)?.status === 'published' && a.ruleset_version === p.version
  }).toBe(true)
  const editedProbe = JSON.parse(composePython(probeRule, { PATTERN: editedPattern, AGENT_ID: agentId }))
  const editedAgent = JSON.parse(agentPython(probeAgent))
  expect(editedProbe.version).toBe(createdProbe.version + 1)
  expect(editedAgent.ruleset_version).toBe(editedProbe.version)
  expect(editedProbe.severity).toBe('high')
  expect(editedProbe.action).toBe('alert_only')
  expect(editedProbe.audit_actions).toContain('rule_updated')
  expect(editedProbe.commands.at(-1)).toMatchObject({ status: 'published', signature_valid: true, schema_version: 1 })
  expect(editedAgent.rules).toContainEqual({ pattern: editedPattern, action: 'alert_only' })

  const editedRow = page.getByRole('row').filter({ hasText: editedPattern })
  await editedRow.getByRole('button', { name: 'Eliminar' }).click()
  await editedRow.getByRole('button', { name: 'Cancelar' }).click()
  expect(await page.locator('text=¿Eliminar?').count()).toBe(0)
  expect(deleteRequests).toBe(0)
  await editedRow.getByRole('button', { name: 'Eliminar' }).click()
  const deletion = page.waitForResponse((r) => r.url().includes('/api/rules/') && r.request().method() === 'DELETE')
  await editedRow.getByRole('button', { name: 'Confirmar' }).click()
  expect((await deletion).status()).toBe(204)
  expect(deleteRequests).toBe(1)
  await expect(page.getByText(editedPattern)).toHaveCount(0)

  await expect.poll(() => {
    const p = JSON.parse(composePython(probeRule, { PATTERN: editedPattern, AGENT_ID: agentId }))
    const a = JSON.parse(agentPython(probeAgent))
    return p.rule_id === null && p.audit_actions.includes('rule_deleted') && a.ruleset_version === p.version
      && !a.rules.some((r: { pattern: string }) => r.pattern === editedPattern)
  }).toBe(true)
  const deletedProbe = JSON.parse(composePython(probeRule, { PATTERN: editedPattern, AGENT_ID: agentId }))
  const deletedAgent = JSON.parse(agentPython(probeAgent))
  expect(deletedProbe.version).toBe(editedProbe.version + 1)
  expect(deletedAgent.ruleset_version).toBe(deletedProbe.version)

  execFileSync('sh', ['-c', 'printf %s "$1" >> "$2"', 'sh', 'us17-default-alert-only', us17File])
  await expect.poll(() => JSON.parse(composePython(probeEvent, { PROBE_PATH: '/watch/' + path.basename(us17File) })).status).toBe('alert_only')
  const result = {
    edit: { backend: editedProbe, agent: editedAgent },
    delete: { backend: deletedProbe, agent: deletedAgent },
    effect: JSON.parse(composePython(probeEvent, { PROBE_PATH: '/watch/' + path.basename(us17File) })),
  }
  await testInfo.attach('us16-us17-integration-sanitized.json', {
    body: JSON.stringify(result, (key, value) => key === 'hash_detected' ? createHash('sha256').update(value).digest('hex') : value, 2),
    contentType: 'application/json',
  })
})

test('US-25 bulk approve publishes a signed command, receives ACK, and updates the real baseline', async ({ page }, testInfo) => {
  const agentId = required('FIM_LAB_AGENT_ID')
  const eventPath = '/watch/' + path.basename(us25File)
  const pattern = eventPath
  const token = await login(page)
  const ruleResponse = await page.request.post('/api/rules', {
    headers: { Authorization: `Bearer ${token}` },
    data: { pattern, severity: 'high', action: 'manual_review' },
  })
  expect(ruleResponse.status()).toBe(201)
  await expect.poll(() => {
    const p = JSON.parse(composePython(probeRule, { PATTERN: pattern, AGENT_ID: agentId }))
    const a = JSON.parse(agentPython(probeAgent))
    return a.ruleset_version === p.version
  }).toBe(true)

  execFileSync('sh', ['-c', 'printf %s "$1" >> "$2"', 'sh', 'us25-approved-content', us25File])
  await expect.poll(() => JSON.parse(composePython(probeEvent, { PROBE_PATH: eventPath })).status).toBe('pending')
  const pending = JSON.parse(composePython(probeEvent, { PROBE_PATH: eventPath }))

  await page.goto(`/events?status=pending&path_prefix=${encodeURIComponent(eventPath)}`)
  const checkbox = page.getByRole('checkbox', { name: `Seleccionar evento #${pending.event_id}` })
  await expect(checkbox).toBeVisible()
  await checkbox.check()
  await page.getByRole('button', { name: 'Aprobar seleccionados' }).click()
  const response = page.waitForResponse((r) => r.url().endsWith('/api/actions/bulk-approve'))
  await page.getByRole('dialog').getByRole('button', { name: 'Aprobar', exact: true }).click()
  expect((await response).status()).toBe(200)

  await expect.poll(() => JSON.parse(composePython(probeEvent, { PROBE_PATH: eventPath })).commands.at(-1)?.ack_status).toBe('acked')
  const backend = JSON.parse(composePython(probeEvent, { PROBE_PATH: eventPath }))
  const agent = JSON.parse(agentPython(probeAgent, { PROBE_PATH: eventPath }))
  expect(backend.status).toBe('approved')
  expect(backend.audit_actions).toContain('approve')
  expect(backend.commands.at(-1)).toMatchObject({ type: 'baseline_update', status: 'published', ack_status: 'acked', signature_valid: true, schema_version: 1 })
  expect(agent.baseline.hash).toBe(backend.hash_detected)
  expect(agent.baseline.approved_event_id).toBe(backend.event_uuid)
  await testInfo.attach('us25-agent-effect-sanitized.json', {
    body: JSON.stringify({ backend: { ...backend, hash_detected: 'sha256-match-redacted' }, agent: {
      ...agent, baseline: { ...agent.baseline, hash: 'sha256-match-redacted' },
    }, signature: 'verified by real agent before command execution' }, null, 2),
    contentType: 'application/json',
  })
})
