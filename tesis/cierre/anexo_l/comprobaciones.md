# Comprobaciones del Anexo L

Este archivo conserva, sin cambios de redacción, las órdenes y salidas que el Anexo L del documento transcribía hasta la etiqueta entrega-tesis-v11 (apartados L.5 y L.7) y que, desde entrega-tesis-v12, el anexo resume y remite aquí (hallazgo T-9). Las órdenes se ejecutan desde la raíz de un clon de la etiqueta de referencia. La numeración de tablas corresponde a entrega-tesis-v11.

## L.5 SHA-256 de los paquetes sin manifiesto

La Tabla 37 consigna el SHA-256 de cada archivo de los tres paquetes del 3 de octubre que no tienen manifiesto (Anexo F.1). Su procedencia y su sellado se describen en el Anexo F.1; la tabla permite verificar cada archivo por separado. La orden siguiente lo calcula en el directorio de cada paquete:

```bash
find . -type f | LC_ALL=C sort | sed 's|^\./||' | xargs sha256sum
```

Tabla 37. SHA-256 de los archivos de los paquetes sin manifiesto de v5.1-tesis

| Paquete | Archivo | SHA-256 |
|---|---|---|
| diagnostico-drenaje-v5.0-20261003 | LEEME.md | caf95d6f4e3c14b98d051d82cd787df3c94db384e4dc7cd9fec300fc39e37708 |
| diagnostico-drenaje-v5.0-20261003 | bateria5_perfil.log | 74bae15775340eb8942748795f6bd0ecf94b970c965f3d3f7feda0ce5574432f |
| diagnostico-drenaje-v5.0-20261003 | eventos.csv | 0fe0b09b768f91c73076cbfaaaa65d02940a81c055c92498122d71a2c00cc5f2 |
| diagnostico-drenaje-v5.0-20261003 | lag_stream_prueba2.txt | a8691779462d3fe4a2d634e24138f24df7018082774a340ab68a203064d74d2d |
| diagnostico-drenaje-v5.0-20261003 | timing.jsonl | 9c1f272984a35a0d105f9e2d648f61da393aaf33fc190422b72792d208b89b7a |
| diagnostico-notificacion-v5.0-vs-v5.1-20261003 | LEEME.md | bc036def9183e3fd042b3354cc2fa9544b863c3fa23e7ad957805e0aeee2a8ee |
| diagnostico-notificacion-v5.0-vs-v5.1-20261003 | medir_tasa_entrega.sh | c65c23a275a45ca3443b2676b34225674938a8614c8ccbc77f2c17bcfa92a3a9 |
| v5.1-analisis-20261003 | LEEME.md | d790e4e6da5039e537306c4b24a8ac804f7e7d62f976b60da70544611ae66a88 |
| v5.1-analisis-20261003 | a1_p99_bootstrap.json | c119e2a15497003ce0c2f516371da4ae95d246ae80e942e114efc9d011386242 |
| v5.1-analisis-20261003 | a1_p99_bootstrap.tsv | 658d766c9980da61b22997e6d609ce6a914bb4ce28af1d99f054bdb9c1b98f44 |
| v5.1-analisis-20261003 | control_run-01.csv | 732d3aefa477f040a0ba252a94dd43e08bbc54f48478ba777587e346e3267bc3 |
| v5.1-analisis-20261003 | control_run-01.txt | 5b8f330a69db93118c55c4296670fcaca08f032c67760dc67deeaebbe8c2b83a |
| v5.1-analisis-20261003 | control_run-02.csv | bb570fa683d074b5f687c4d7b87579a484aa56fa48d906454317ef20d54ac1fb |
| v5.1-analisis-20261003 | control_run-02.txt | d61f5992496072e71e4eb20cdaf090eee38977ac38bdd543e920aec9645fcb83 |
| v5.1-analisis-20261003 | control_run-03.csv | 71d54773aa892a5e43bb6976e6d0e16f92d81275aaa11111476867f105789669 |
| v5.1-analisis-20261003 | control_run-03.txt | e3460e8157d48a9c61bb5fdcee4307628b86582a2383e6a4ed284c1c23a186cb |

Nota. Valores calculados sobre la etiqueta entrega-tesis-v11. Los tres paquetes no cambiaron desde que se versionaron, el 3 de octubre de 2026, en los commits a012aff, 4ed2aa4, ada3d4e y 995bdc8, cuyo hash sella su contenido. La tabla complementa ese sello: permite verificar cada archivo sin recorrer el historial. Desde entrega-tesis-v8, los tres paquetes tienen, además, su manifiesto, que reproduce estos valores para los 16 archivos (P-8).

Salida esperada: una línea por archivo, con el SHA-256 que la Tabla 37 consigna para ese archivo.

## L.7 Comprobación de los datos de repositorio

Las órdenes siguientes comprueban los datos de repositorio que el documento cita; scripts/verificar_commits.sh comprueba, además, todos sus identificadores de commit. Se ejecutan desde la raíz del clon, sobre la etiqueta entrega-tesis-v11, que contiene las de las entregas anteriores; los commits de septiembre requieren incorporar antes los bundles de custodia (Anexo F.2). Las salidas consignadas son las que dan sobre esa etiqueta; tesis/HISTORIA_REVISIONES.md (Anexo N) indica cuándo se obtuvo cada una por primera vez.

### Commits que versionan los paquetes sin manifiesto (Anexos F.1 y L.5).

```bash
E=tesis/cierre/evidencia
for c in a012aff 4ed2aa4 ada3d4e 995bdc8; do git cat-file -e $c^{commit} && git log -1 --format='%h %cs' $c; done
for p in v5.1-analisis-20261003 diagnostico-drenaje-v5.0-20261003 diagnostico-notificacion-v5.0-vs-v5.1-20261003; do echo $p; git log --format='%h %cs' -- $E/$p; done
```

Salida esperada: los cuatro commits existen, todos del 2026-10-03. v5.1-analisis-20261003 entra en a012aff y 4ed2aa4; diagnostico-drenaje-v5.0-20261003, en ada3d4e; y diagnostico-notificacion-v5.0-vs-v5.1-20261003, en 995bdc8. En entrega-tesis-v8, los tres directorios registran, además, el commit de su sellado, 9a6d657 2026-10-18, que solo agrega su manifiesto, su acta y, en el primero, el recálculo del drenaje; ningún otro commit los modifica.

### Marcas FIN_CORTE de la batería de resiliencia (Tabla 21 y Anexo L.4).

```bash
for n in 1 2 3; do grep FIN_CORTE $E/v5-eval-20261003T102313Z/resiliencia/run-0$n/bateria5_run-0$n.log; done
```

Salida esperada: [2026-10-03T12:37:56.80393730Z] FIN_CORTE t=2026-10-03T12:37:56.75234211Z; [2026-10-03T12:44:20.716417871Z] FIN_CORTE t=2026-10-03T12:44:20.710779876Z; y [2026-10-03T12:50:43.749670694Z] FIN_CORTE t=2026-10-03T12:50:43.743002952Z. Solo la primera línea lleva fracciones de ocho dígitos, y en las tres el campo t= precede a la marca entre 5 y 7 ms.

### Hash completo de 6e81ccf (Anexo F.2 y Tabla 34).

```bash
P=$E/final-consolidated-fixed-20260911T225314Z
grep -o '6e81ccf[0-9a-f]*' $P/README.md $P/results.json | sort -u
git cat-file -e 6e81ccf95f8da644b74b41a499d3414a08248e06 2>/dev/null || echo ausente
```

Salida esperada: README.md y results.json contienen el mismo hash, 6e81ccf95f8da644b74b41a499d3414a08248e06, y la segunda orden imprime «ausente»: el commit no está en el repositorio.

### Commit 8d37075 (Tabla 35).

```bash
git log -1 --format='%h %cs %s' 8d37075
```

Salida esperada: 8d37075 2026-09-10 fix(agent): bind approved baseline content to event.

### Commits de septiembre conservados en los bundles (Anexo F.2 y Tabla 34).

```bash
for b in final-consolidated-fixed-20260911T225314Z final-consolidated-v10-20260912T210903Z; do git bundle verify -q $E/$b/custody/candidate.bundle && git fetch -q $E/$b/custody/candidate.bundle "+refs/heads/*:refs/remotes/$b/*"; done
for c in 7df4935 7a7ee50 d35fb9c; do git log -1 --format='%h %cs %an' $c; done
git merge-base --is-ancestor d35fb9c 7a7ee50 && echo pertenece
```

Salida esperada: ambos bundles se informan íntegros; 7df4935 2026-09-11 FIM Evidence Snapshot; 7a7ee50 2026-09-12 Ezequiel Gonzalez; d35fb9c 2026-09-12 Ezequiel Gonzalez; y «pertenece».

### Trazas de resiliencia de v2.0-tesis (Anexo F.1).

```bash
Q=$E/v2-eval-20260922T175053Z/resiliencia
for n in 1 2 3; do f=$Q/run-0$n/traza_run-0$n.jsonl.gz; sha256sum $f | cut -c1-16; zcat $f | sha256sum; zcat $f | sed -n '1p;$p' | grep -o '"timestamp":"[^"]*"\|"run_id":"[^"]*"'; done
```

Salida esperada: los archivos comprimidos tienen hashes distintos (eb8bc79147ff0740…, d5c7ad89736e3d8e… y 8c949308eda570f8…). Descomprimidos, los tres dan 888f7f03c178c1879416a7a00b5704c05bd4ebd5bf954c1048fdc0712b8bcb0c. En los tres, la primera línea es del 2026-09-22T17:58:31.808834+00:00 y la última del 2026-09-22T19:17:26.140323+00:00, ambas con run_id b3-traza.

### Cambios archivados y especificaciones de capacidades (apartado 3.8).

```bash
ls -d openspec/changes/archive/*/ | wc -l
ls -d openspec/specs/*/ | wc -l
cat openspec/specs/*/spec.md | grep -c '^### Requirement'
```

Salida esperada: 66, 58 y 448: sesenta y seis cambios archivados, cincuenta y ocho especificaciones de capacidades y cuatrocientos cuarenta y ocho requisitos.

### Commits del primer código del backend, del detector fanotify y de la consola (apartados 3.8 y 9.1.2, Anexo F.2).

```bash
for c in ea5b492 a7199d7 3b62b97; do git log -1 --format='%h %cs %an <%ae>' $c; done
```

Salida esperada: ea5b492 2026-04-25 3zequiel3 <3zegonzalez@gmail.com>; a7199d7 2026-06-17 mncrmn2009 <mnc.rmn.2009@gmail.com>; y 3b62b97 2026-06-21 mncrmn2009 <mnc.rmn.2009@gmail.com>. La tercera columna da el nombre y la dirección de autor que registra el historial: mncrmn2009 es la cuenta de Nicolás Castro, y 3zequiel3, la de Ezequiel González.
