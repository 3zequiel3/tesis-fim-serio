#!/usr/bin/env python3
"""Atribuye las operaciones no encoladas de la batería de resiliencia (hallazgo N-6).

Los paquetes de resiliencia conservan, por repetición, el registro del generador
(bateria5_run-NN.log, con una línea por operación y su instante real), la traza
causal del agente y los eventos persistidos, pero no el manifiesto con el hash
de cada operación. El generador es determinista dada su configuración, que el
registro consigna completa; este script:

  1. relee esa configuración y vuelve a ejecutar scripts/generador_carga.py con
     la misma semilla en un directorio temporal, para obtener los hashes;
  2. verifica que operación, patrón y ruta coincidan con el registro original,
     operación por operación, y aborta ante cualquier discrepancia;
  3. sustituye los instantes por los del registro original;
  4. ejecuta scripts/atribuir_operaciones_sin_evento.py con la traza de la
     repetición;
  5. separa las supresiones en «reversión dentro de la corrida» (el contenido
     vuelve a un estado ya producido en la misma repetición) y «arrastre» (el
     hash coincide con una entrada de línea base que proviene de corridas
     anteriores, porque el arnés no la purgaba).

No modifica el paquete sellado. Escribe en --salida.

Uso:
    python3 scripts/atribuir_resiliencia.py <paquete> --salida <directorio>
"""
import argparse, csv, gzip, json, re, shutil, subprocess, sys, tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LINEA = re.compile(r'\[(\d{5})/(\d+)\]\s+(\w+)\s+(\w+)\s+(\S+)\s+ts=(\S+)')
CONF = re.compile(r'^\s{2}(\w+)\s+=\s+(.*)$')

def configuracion(log):
    conf = {}
    for linea in open(log, encoding='utf-8'):
        m = CONF.match(linea)
        if m and m.group(1) not in conf:
            conf[m.group(1)] = m.group(2).strip()
        if linea.startswith('inicio_utc'):
            break
    return conf

def regenerar(conf, destino):
    mix = eval(conf['mix'])  # dict literal escrito por el propio generador
    mix_arg = f"{round(mix['creacion']*100)}/{round(mix['modificacion']*100)}/{round(mix['borrado']*100)}"
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [sys.executable, str(REPO / 'scripts/generador_carga.py'), '--dir', tmp,
               '--seed', conf['seed'], '--rate', '5000', '--count', conf['count'], '--mix', mix_arg,
               '--revert-frac', conf['revert_frac'], '--burst-frac', conf['burst_frac'],
               '--burst-size', conf['burst_size'], '--ephemeral-frac', conf['ephemeral_frac'],
               '--critical-subdir', conf['critical_subdir'], '--critical-frac', conf['critical_frac'],
               '--file-size', conf['file_size_bytes'], '--prefix', conf['prefix'],
               '--agent-prefix', conf['agent_prefix'], '--manifest', str(destino / 'regenerado.json'),
               '--log', str(destino / 'regenerado.log'), '--quiet']
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    return [json.loads(l) for l in open(destino / 'regenerado.jsonl')]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('paquete'); ap.add_argument('--salida', required=True)
    a = ap.parse_args()
    paquete, salida = Path(a.paquete), Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)
    resumen = []
    for run in sorted((paquete / 'resiliencia').glob('run-*')):
        r = run.name
        log = run / f'bateria5_{r}.log'
        base = regenerar(configuracion(log), salida)
        reales = {int(m.group(1)): m.groups() for m in map(LINEA.search, open(log, encoding='utf-8')) if m}
        if len(reales) != len(base):
            sys.exit(f'{r}: el registro tiene {len(reales)} operaciones y el manifiesto regenerado {len(base)}')
        man = salida / f'manifiesto_{r}.jsonl'
        with open(man, 'w') as f:
            for o in base:
                _, _, op, patron, ruta, ts = reales[o['seq']]
                if (op, patron, ruta) != (o['operacion'], o['patron'], o['ruta_agente']):
                    sys.exit(f'{r}: discrepancia en la operación {o["seq"]}; no se atribuye')
                o = dict(o, ruta_host=ruta, ts_utc=ts, ts_epoch=datetime.fromisoformat(ts).timestamp())
                f.write(json.dumps(o) + '\n')
        traza = salida / f'traza_{r}.jsonl'
        with gzip.open(run / f'traza_{r}.jsonl.gz') as g, open(traza, 'wb') as f:
            shutil.copyfileobj(g, f)
        atrib = salida / f'atribucion_{r}.csv'
        p = subprocess.run([sys.executable, str(REPO / 'scripts/atribuir_operaciones_sin_evento.py'),
                            '--manifiesto', str(man), '--eventos', str(run / 'eventos.csv'),
                            '--traza', str(traza), '--salida', str(atrib)], capture_output=True, text=True)
        (salida / f'atribucion_{r}.txt').write_text(p.stdout + p.stderr)
        traza.unlink()
        filas = list(csv.DictReader(open(atrib)))
        sin_evento = {int(x['seq']) for x in filas}
        vistos, reversion, arrastre = {}, 0, 0
        for o in map(json.loads, open(man)):
            if o['seq'] in sin_evento:
                if o['hash_despues'] in vistos.get(o['ruta_agente'], set()):
                    reversion += 1
                else:
                    arrastre += 1
            vistos.setdefault(o['ruta_agente'], set()).add(o['hash_despues'])
        causas = {}
        for x in filas:
            causas[x['causa']] = causas.get(x['causa'], 0) + 1
        resumen.append((r, len(base), len(base) - len(sin_evento), len(sin_evento), causas, reversion, arrastre, p.returncode))
    for f in ('regenerado.json', 'regenerado.jsonl', 'regenerado.log'):
        (salida / f).unlink(missing_ok=True)
    with open(salida / 'RESUMEN.md', 'w') as f:
        f.write(f'# Atribución de operaciones no encoladas — {paquete.name}\n\n')
        f.write('| Repetición | Operaciones | Con evento | Sin evento | Causas | Reversión en la corrida | Arrastre de línea base | Código |\n|---|---|---|---|---|---|---|---|\n')
        for fila in resumen:
            f.write('| ' + ' | '.join(str(x) for x in fila) + ' |\n')
    print((salida / 'RESUMEN.md').read_text())
    return 0 if all(x[-1] == 0 for x in resumen) else 1

if __name__ == '__main__':
    sys.exit(main())
