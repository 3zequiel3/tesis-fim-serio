## MODIFIED Requirements

### Requirement: Initial baseline scan

El motor SHALL ejecutar un escaneo inicial de cada `watch_path` configurado que todavía no completó un primer escaneo, es decir, que no figura en `initialized_roots` de `state.json`. Para cada archivo regular encontrado en una raíz no inicializada el motor MUST calcular el SHA-256 de su contenido claro, persistir una entrada de baseline cifrada con `status: present`, y registrar la metadata (path, hash, size, mode, uid, gid, mtime). Este alta MUST ser silenciosa: no produce eventos. Al completar el recorrido de una raíz existente, el motor MUST informarla como inicializada para que se agregue a `initialized_roots`; una raíz inexistente MUST NOT marcarse. Una raíz que ya figura en `initialized_roots` MUST NOT recorrerse en el escaneo inicial: sus archivos sin entrada quedan para la reconciliación al arrancar, que los reporta. Si un `watch_path` se agrega en runtime sin baseline previo, el motor MUST escanearlo de la misma forma y la raíz MUST marcarse como inicializada. (D80 / RN-174)

#### Scenario: Primer arranque genera baseline cifrado

- **WHEN** el agente arranca por primera vez con `watch_paths` que contienen archivos regulares
- **THEN** existe un archivo de baseline cifrado por cada archivo escaneado, cada uno con permisos `0600`, y cada entrada tiene `status: present` y un hash SHA-256 no nulo
- **AND** cada raíz escaneada queda en `initialized_roots`
- **AND** no se emite ningún evento

#### Scenario: No re-escanea si ya hay baseline

- **WHEN** el agente reinicia y ya existe baseline para todos los `watch_paths`
- **THEN** el motor no regenera las entradas existentes y conserva sus snapshots

#### Scenario: Path nuevo sin baseline previo

- **WHEN** se agrega un `watch_path` nuevo que no tiene entradas de baseline
- **THEN** el motor escanea solo ese path y genera sus entradas cifradas
- **AND** la raíz queda en `initialized_roots`

#### Scenario: Un archivo nuevo en una raíz inicializada no se da de alta en silencio

- **WHEN** el agente arranca, la raíz figura en `initialized_roots` y contiene un archivo sin entrada de baseline
- **THEN** el escaneo inicial no crea la entrada de ese archivo

#### Scenario: Una raíz inexistente no se marca

- **WHEN** un `watch_path` configurado no existe al arrancar
- **THEN** el escaneo registra `baseline.watch_path_missing` y la raíz no se agrega a `initialized_roots`

## ADDED Requirements

### Requirement: Reconciliación del baseline contra el filesystem al arrancar

`BaselineEngine` SHALL exponer `reconcile_on_start(watch_paths, initialized_roots)`, que compara el baseline contra el filesystem de cada raíz presente a la vez en `watch_paths` y en `initialized_roots` y devuelve los hallazgos sin modificar el baseline ni publicar nada. Para cada entrada ubicada bajo una de esas raíces:

- entrada `present` y path inexistente → hallazgo `file_deleted`;
- entrada `present` con hash distinto del disco, o con cambio de tipo de objeto entre symlink y archivo regular → hallazgo `file_modified`, salvo la supresión del requisito siguiente;
- entrada `absent` y path existente → hallazgo `file_created`;
- en cualquier otro caso, ningún hallazgo.

Además, todo archivo regular o symlink de esas raíces sin entrada de baseline SHALL producir un hallazgo `file_created`, recorriendo la raíz con las mismas reglas que el escaneo inicial (symlink antes que archivo, descarte de lo que resuelve fuera de la raíz).

El hash del disco MUST calcularse con la regla de symlink como objeto (D33/RN-127): `sha256` del string de `readlink` para un symlink, SHA-256 del contenido para un archivo regular. Un error de integridad o de lectura sobre un path MUST registrarse y contarse sin detener el recorrido. El resultado MUST incluir los contadores `unchanged`, `suppressed_already_reported` y `errors`, y los hallazgos MUST devolverse ordenados por path. (D80 / RN-174)

#### Scenario: Archivo modificado con el agente detenido

- **WHEN** la entrada de un path está `present` con hash `H1` y el archivo en disco tiene hash `H2`
- **THEN** el resultado contiene un hallazgo `file_modified` para ese path

#### Scenario: Archivo eliminado con el agente detenido

- **WHEN** la entrada de un path está `present` y el path no existe en disco
- **THEN** el resultado contiene un hallazgo `file_deleted` para ese path

#### Scenario: Archivo ausente que reaparece

- **WHEN** la entrada de un path está `absent` y el path existe en disco
- **THEN** el resultado contiene un hallazgo `file_created` para ese path

#### Scenario: Archivo creado sin entrada en una raíz inicializada

- **WHEN** una raíz figura en `initialized_roots` y contiene un archivo sin entrada
- **THEN** el resultado contiene un hallazgo `file_created` para ese archivo

#### Scenario: Archivo sin cambios

- **WHEN** la entrada está `present` y el hash del disco coincide
- **THEN** no hay hallazgo para ese path y `unchanged` lo cuenta

#### Scenario: Raíz no inicializada fuera del reconcile

- **WHEN** una entrada pertenece a una raíz que no está en `initialized_roots`
- **THEN** el reconcile no produce hallazgos para ella

#### Scenario: El reconcile no muta el baseline

- **WHEN** se ejecuta `reconcile_on_start` sobre un baseline con hallazgos
- **THEN** ningún blob de baseline cambia como efecto de la llamada

#### Scenario: Error sobre un path no detiene el recorrido

- **WHEN** la entrada de un path falla la verificación GCM
- **THEN** el error se registra, `errors` lo cuenta y los demás paths se reconcilian igual

### Requirement: Una modificación offline ya reportada no se re-emite

Un hallazgo `file_modified` SHALL suprimirse, y contarse en `suppressed_already_reported`, si y sólo si el candidato de aprobación del path (`stage_approval_candidate`) existe, tiene `status: present`, su hash es igual al hash actual del disco y su tipo de objeto coincide con el del disco. Un candidato ilegible MUST tratarse como inexistente: la duda se resuelve hacia reportar. La supresión MUST NOT aplicarse a `file_deleted` ni a `file_created`. (D80 / RN-174)

#### Scenario: Reinicio con una modificación ya reportada

- **WHEN** un path fue reportado como `file_modified` con hash `H2`, no fue aprobado y el disco sigue en `H2` al reiniciar
- **THEN** el reconcile no produce hallazgo para ese path y `suppressed_already_reported` lo cuenta

#### Scenario: Modificación posterior a la ya reportada

- **WHEN** el candidato del path tiene hash `H2` y el disco tiene `H3`
- **THEN** el reconcile produce un hallazgo `file_modified`

#### Scenario: Candidato ilegible

- **WHEN** el candidato del path no supera la verificación GCM
- **THEN** el reconcile produce el hallazgo `file_modified`
