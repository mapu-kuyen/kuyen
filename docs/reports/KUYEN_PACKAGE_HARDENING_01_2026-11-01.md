# KUYEN_PACKAGE_HARDENING_01 — Informe de ejecución

**Paquete:** `kuyen` 0.2.0 · **Commit base:** `5fd8777a8305097792380fceb9ff861de208147a` (tag `v0.2.0`, `main`, PyPI 0.2.0)
**Fecha de ejecución:** 2026-11-01 (UTC-3) · **Alcance:** corrección de A1, A2 y A3; diagnóstico de M1 y M2
**Veredicto:** **PASS** para A1–A3 · M1/M2 permanecen abiertos por diseño · **integración con LeftraruOS NO validada**

---

## A. Identificación y línea base

| dato | valor |
|---|---|
| ruta absoluta del repositorio | `/tmp/kuyen_hardening_01/kuyen` (clon de `https://github.com/mapu-kuyen/kuyen.git`) |
| rama | `HEAD` (detached, checkout explícito del commit auditado) |
| HEAD | `5fd8777a8305097792380fceb9ff861de208147a` — verificado tras el checkout |
| `git status --porcelain` antes de intervenir | **vacío** (árbol limpio) |
| versión del paquete | `VERSION` = `0.2.0`; se determina con `setuptools.dynamic.version = {file = "VERSION"}` |
| versión publicada de referencia | PyPI `kuyen` 0.2.0 (única release); tag anotado `v0.2.0` → `5fd8777` |
| Python | 3.13.1 (`/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`) |
| dependencias runtime | `jsonschema>=4.0`, `PyYAML>=6.0` (extra `openviking`: `httpx>=0.25`) |
| dependencias de desarrollo | `pytest>=7.0`, `build>=1.0`, `twine>=5.0` |
| ejecución | `PYTHONPATH=src python3 -m pytest` — **sin instalar nada**, sin tocar el entorno global |
| `kuyen.__file__` verificado | `/private/tmp/kuyen_hardening_01/kuyen/src/kuyen/__init__.py` (sólo el clon 0.2.0) |
| suite antes de cambios | **187 recogidos: 185 passed, 2 skipped, 0 failed** (2,6 s) |
| cobertura antes | **75 %** (7 547 sentencias, 1 918 sin cubrir) |
| fallos preexistentes | ninguno |

El árbol local `knowledge/kuyen` (0.1.9, sin `.git`) se dejó **intacto y fuera de alcance**: no es
el repositorio auditado, no se usó como referencia y no se migró.

---

## B. Matriz A1–A3

### A1 — la validación aceptaba evidencia falsa, aserciones verificadas sin evidencia e identidades duplicadas

**Contrato esperado.** `DATA_MODEL.md`: «Offsets address the source text directly: a quote that
does not appear at its offsets is rejected»; todo objeto canónico lleva evidencia y un estado de
soporte explícito. `validation/validators.py` ya implementa esas reglas (`EvidenceValidator`,
`GraphStructuralValidator`) **para el grafo tipado del candidato**, no para el documento canónico.

**Archivos y funciones inspeccionadas.** `src/kuyen/lifecycle/antu.py::_verify_proposal`
(línea 60 auditada), `src/kuyen/ingest.py::build_document` (línea 5 auditada),
`src/kuyen/storage/commit.py::_validate`, `src/kuyen/api/memory.py::import_canonical` y
`execute_antu`, `src/kuyen/validation/validators.py::{EvidenceValidator, GraphStructuralValidator}`,
`src/kuyen/schemas/kuyen.schema.json`.

**Causa raíz.** El camino canónico (`build_document` → `import_canonical` → `commit_version` →
`_validate`) trabaja con diccionarios y **no ejecutaba** los validadores del grafo. `_validate` sólo
comprobaba el esquema y la integridad referencial: un `set()` de ids colapsaba los duplicados, nada
comparaba la cita con el texto en sus offsets y ningún estado declaraba obligación de evidencia.

**Reproducción antes de corregir** (`tests/api/test_a1_canonical_validation.py`, 9 pruebas):
8 fallaban con `DID NOT RAISE CommitError` sobre `import_canonical`.

**Prueba de regresión añadida.** 13 pruebas en `tests/api/test_a1_canonical_validation.py`:
cita que no coincide con sus offsets, evidencia de un MAPU inexistente, hash de fuente declarado
distinto del MAPU, aserción `SOURCE_VERIFIED` sin evidencia, entidad `SOURCE_VERIFIED` sin
evidencia, `entity_id`/`assertion_id`/`evidence_id` duplicados, tres casos equivalentes por el camino
Antü (incluida la identidad que ya existe en la versión base) y cuatro guardas de no regresión
(documento válido aceptado, Antü válida validada y comprometida).

**Corrección aplicada (mínima).** Nuevo módulo `src/kuyen/validation/canonical.py` con
`validate_canonical_objects(...)`, que aplica **las mismas reglas** de `EvidenceValidator` y
`GraphStructuralValidator` a los diccionarios canónicos (duplicados, resolución de evidencia por
MAPU/offsets/hash/URI, y estado de verificación que exige evidencia). Se invoca en un único punto de
la ruta de escritura, `commit.py::_validate` (cubre `import_canonical` y `commit`), y en
`antu.py::_verify_proposal` (para rechazar **antes** de crear una ejecución `VALIDATED`),
con `base_ids` para detectar identidades que ya existen en la versión base.

**Resultado después de corregir.** 13/13 pruebas pasan; el documento válido se sigue aceptando y se
compromete (guarda de no regresión). `verify()` sigue en `ok`.

**Decisión declarada (no es semántica nueva).** Se exige evidencia cuando el objeto declara
`status`/`evidence_status = SOURCE_VERIFIED`. Es el equivalente canónico de
`ASSERTION_EVIDENCE_MISSING` que `GraphStructuralValidator` aplica con `evidence_policy = strict`, y
se aplica a entidades, relaciones y aserciones por ser el mismo invariante. Si el contrato quisiera
permitir `SOURCE_VERIFIED` sin evidencia, eso sería un cambio de contrato y debe decidirse aparte.

**Limitaciones y riesgos residuales.** (i) Las reglas viven ahora en dos dialectos (tipado y
diccionario) —ver B7 «código duplicado», fuera de alcance—; la duplicación queda declarada aquí y el
módulo nuevo replica los códigos (`EVIDENCE_QUOTE_MISMATCH`, `DUPLICATE_ID`, …) para que un futuro
refactor pueda unificarlos sin cambiar mensajes. (ii) No se valida semántica (polaridad, ontología):
fuera del alcance de A1.

### A2 — un commit con base obsoleta dejaba una versión huérfana

**Contrato esperado.** `VERSIONING.md` / `CANONICAL_STORAGE.md`: el puntero `CURRENT` es la única
autoridad del siguiente version; la publicación de la versión es un *commit point* y un commit
rechazado no puede dejar artefactos publicados ni versiones que el linaje no alcanza.

**Archivos y funciones inspeccionadas.** `src/kuyen/storage/commit.py::{commit_version,
_require_expected_base}`, `src/kuyen/storage/store.py::write_current` (compare-and-swap),
`src/kuyen/storage/registry.py::{set_current, verify_registry}`,
`src/kuyen/api/memory.py::{commit, execute_antu, import_canonical}`, `src/kuyen/api/memory.py::verify`.

**Reproducción antes de corregir.** `tests/storage/test_a2_stale_base_commit.py`: 4/4 fallaban.
Dos ejecuciones validadas contra la misma base (secuencial y con `threading.Barrier`), y el segundo
commit publicaba el manifiesto (paso 7), indexaba (8), escribía `ANTU_COMPLETED`,
`PROJECTION_ENQUEUED` y `VERSION_COMMITTED` (9–11) y **sólo entonces** fallaba el compare-and-swap
(paso 12). Resultado observado: 3 versiones donde sólo 2 eran alcanzables (p. ej. `VER-f4c596671405`
huérfana) y `verify()` devolvía `ok = True`.

**Prueba de regresión añadida.** 4 pruebas: rechazo secuencial sin versión huérfana, ausencia de
eventos de resultado en el ledger del perdedor, dos escritores simultáneos con `Barrier`
(exactamente una versión publicada, sin staging pendiente) y ausencia de manifiesto publicado por el
perdedor.

**Corrección aplicada (mínima).** `_require_expected_base(store, expected_parent_version_id)` como
**primera** sentencia dentro de `store.writer_lock()`, con la misma condición y el mismo mensaje que
el compare-and-swap final. Además, la escritura de blobs de objetos (`_object_hashes`) se movió
dentro de la sección crítica: son escrituras y su temp file (`write_atomic`, nombre basado en PID) se
colisionaba entre hilos del mismo proceso antes de adquirir el lock (síntoma observado:
`FileNotFoundError` en `.tmp-…`). No se añadió merge, rebase, rama ni reconciliación.

**Resultado después de corregir.** 4/4 pruebas pasan, cinco ejecuciones consecutivas sin
intermitencia. En secuencia: 2 versiones, `CURRENT` apunta al ganador, `pending().incomplete == []`,
`verify().ok = True` y el ledger no registra el resultado del perdedor.

**Consistencia del store tras el rechazo.** Verificada con `pending()` (sin `incomplete`, sin
`staging`), `verify()` y reapertura del store con `KuyenMemory.open`.

**Limitaciones y riesgos residuales.** (i) `verify()` sigue **sin** comprobar alcanzabilidad desde
`CURRENT`: no se añadió un invariante nuevo, se eliminó la causa que producía huérfanas.
(ii) El caso concurrente deja el ledger corrupto por **M1** (ver sección C, fuera de alcance); la
prueba lo declara explícitamente y sólo tolera esa firma concreta. (iii) `execute_antu` y
`import_canonical` siguen sin lock propio: el lock cubre el commit, no la preparación.

### A3 — `backup(destino)` podía destruir el propio store

**Contrato esperado.** `BACKUP_AND_RECOVERY.md` / `PUBLIC_API.md`: un backup verificado de un store
content-addressed; una operación rechazada no puede modificar ni el store ni un backup previo.

**Archivos y funciones inspeccionadas.** `src/kuyen/backup/archive.py::{create_backup,
_reject_unsafe_target, restore_backup, _collect_files}`, `src/kuyen/api/memory.py::backup`.

**Reproducción antes de corregir.** `tests/storage/test_a3_backup_target.py`: 4/6 fallaban.
`create_backup` ejecutaba `shutil.rmtree(target)` antes de copiar:
- destino == store → **el store se borraba** y la copia fallaba después;
- destino dentro del store → dejaba restos parciales dentro del propio store;
- destino ancestro del store → borraba el store junto con su directorio padre;
- enlace simbólico al store → `OSError: Cannot call rmtree on a symbolic link` (no `BackupError`).

**Prueba de regresión añadida.** 6 pruebas: destino igual al store, dentro del store, ancestro del
store y enlace simbólico resuelto al store (todas deben lanzar `BackupError` y dejar el store
intacto, comparando un inventario con tamaños antes/después y `verify()`), más dos guardas de no
regresión (destino hermano seguro y reemplazo de un backup previo). Todas las rutas destructivas se
crean dentro de `tmp_path` y se verifica su pertenencia a ese árbol antes de la llamada.

**Corrección aplicada (mínima).** `_reject_unsafe_target(store, target)` compara rutas **resueltas**
(`Path.resolve()`, no texto) y rechaza con `BackupError` antes de tocar nada: destino igual al store,
destino contenido en el store y destino que contiene al store (incluye el caso symlink).

**Resultado después de corregir.** 6/6 pruebas pasan; el store queda intacto en todos los rechazos y
el backup seguro sigue funcionando (verificado con `verify_backup`).

**Limitaciones y riesgos residuales.** `restore_backup` no se tocó (el restore en directorio existente
es B2, fuera de alcance). La comprobación es por contención de rutas resueltas: no pretende detectar
*hard links* ni montajes distintos.

---

## C. M1 y M2 — diagnóstico (no corregidos en esta ejecución)

Ambos se reprodujeron de forma determinista con `diagnostics/m1_m2_diagnosis.py` (fuera del
repositorio, stores desechables en `/tmp`). Evidencia cruda:
`baseline/50_m1_m2_diagnosis.json`.

### M1 — ledger e historial sin lock (`api/memory.py:247`)

**Qué se observó.** Dos hilos llaman a `execute_antu` al mismo tiempo (barrera antes de la llamada).
En **3 de 3 rondas** el ledger quedó roto con la misma firma: `event 6: unexpected seq 5` y
`event 6: prev_event_hash does not link to the previous event`. Ningún hilo recibió error: la
corrupción es silenciosa en el momento y sólo aparece al verificar.

**Causa.** `lifecycle/ledger.py::append_event` hace *read-then-append* (`chain = events(store)` →
`seq = len(chain)+1`, `prev = chain[-1].event_hash` → `append_line`). Dos escritores leen la misma
cadena antes de que ninguno escriba: ambos calculan el mismo `seq` y el mismo `prev_event_hash`.
`CanonicalStore.writer_lock` existe pero **no** se usa en el camino de eventos (sólo lo usan
`commit_version` y otra operación de `storage/commit.py`).

**Qué comparten los escritores.** `ledger/antu.jsonl` (append) y `unit/` (revisiones) — ambos se
escriben desde `execute_antu` sin exclusión; el lock actual cubre el commit, no la preparación.

**Propuesta de corrección (no aplicada).** Adquirir `store.writer_lock()` en un contexto que cubra
`execute_antu` completo (append de eventos + `record_revision`), o —preferible— introducir un
*append* atómico que valide y escriba bajo el mismo lock con reintento acotado. **Pruebas necesarias
en la siguiente ejecución:** (1) dos `execute_antu` con `Barrier` → `verify().ok is True` y
`seq` contiguo, repetido N veces; (2) `append_event` concurrente sobre 20 eventos → cadena íntegra;
(3) un proceso externo (`multiprocessing`) además de hilos, porque `flock` es por descriptor;
(4) prueba negativa: sin el lock la prueba 1 debe fallar.

### M2 — una línea truncada bloquea todo, incluida `recover()` (`lifecycle/ledger.py:21`)

**Qué se observó.** Tras añadir una línea JSON truncada al final de `ledger/antu.jsonl`:

| operación | resultado observado |
|---|---|
| `memory.verify()` | `ok = False`, problema `ledger line 5 is not valid JSON` (correcto: reporta) |
| `memory.recover()` | `JSONDecodeError: Unterminated string …` |
| `memory.pending()` | `JSONDecodeError` |
| `memory.execute_antu(...)` | `JSONDecodeError` |
| `memory.ledger()` | `JSONDecodeError` |
| `ledger.read_tolerant(store)` | `events = 4`, problema `ledger line 5 is not valid JSON` (**ya existe y funciona**) |

**Causa.** `events()` es estricto (`json.loads` de cada línea) y es la base de `append_event`,
`last_event`, `events_of_type` y `recover_pending`; el lector tolerante `read_tolerant()` existe pero
sólo lo usa `verify_chain`. Una última línea truncada (corte de energía, escritura parcial) deja la
memoria **no escribible y no recuperable**, no sólo no verificable. No se distingue la última línea
truncada de corrupción interna.

**Propuesta de corrección (no aplicada).** En `events()`, separar «última línea incompleta» de
«corrupción interna»: si la línea inválida es la última y no hay nada después, devolver la cadena
válida y declarar el truncamiento como problema recuperable; el *append* siguiente debe continuar
la cadena con `seq`/`prev_event_hash` coherentes y dejar constancia. **No** se debe borrar ni
reescribir evidencia: la reparación propone, no elimina. **Pruebas necesarias:** (1) truncar la
última línea → `recover()` completa sin perder eventos previos; (2) truncar una línea intermedia →
fail-closed (no se repara); (3) `verify()` distingue `TRUNCATED_TAIL` de `CORRUPT`;
(4) tras recuperar, un nuevo `append_event` produce cadena válida; (5) ninguna evidencia previa
desaparece del archivo.

---

## D. Validación general

### Comandos exactos

```bash
# identidad y precondición de importación (antes de cada corrida)
PYTHONPATH=src python3 -c "import sys, kuyen; print(sys.executable, kuyen.__file__, kuyen.__version__)"

# suite completa, antes y después
PYTHONPATH=src python3 -m pytest -q

# reporte legible por máquina
PYTHONPATH=src python3 -m pytest -q --junitxml=baseline/32_suite_final.xml

# cobertura (no configurada en pyproject; se invoca explícitamente)
PYTHONPATH=src python3 -m pytest -q -p no:cacheprovider --cov=kuyen --cov-report=term

# reproducción de M1 y M2 (diagnóstico, fuera del repositorio)
python3 /tmp/kuyen_hardening_01/diagnostics/m1_m2_diagnosis.py

# verificación de que el parche se basta a sí mismo
cd <worktree limpio de 5fd8777> && git apply --check hardening.patch && git apply hardening.patch && PYTHONPATH=src python3 -m pytest -q
```

### Conteos

| momento | recogidos | passed | failed | errors | skipped | cobertura |
|---|---|---|---|---|---|---|
| antes | 187 | 185 | 0 | 0 | 2 | **75 %** (7 547 stmts, 1 918 sin cubrir) |
| después | **210** | **208** | **0** | **0** | **2** | **75 %** (7 628 stmts, 1 912 sin cubrir) |
| parche aplicado sobre 5fd8777 limpio | 210 | 208 | 0 | 0 | 2 | — |

Las 23 pruebas nuevas: 13 de A1, 4 de A2, 6 de A3. Los 2 `skipped` son preexistentes (idénticos
antes y después). **No hay fallos preexistentes ni fallos nuevos.**

Reproducción antes de corregir: 19 pruebas, **16 fallaban** y 3 pasaban (las guardas de «válido
sigue aceptándose» y de backup seguro). Registro: `baseline/20_reproduction_before_fix.log`.
Estabilidad de la prueba concurrente: 5 ejecuciones consecutivas de A2, todas verdes.

Cobertura por archivo tocado (después): `validation/canonical.py` 91 %, `storage/commit.py` 75 %,
`api/memory.py` 92 %, `backup/archive.py` 87 %, `lifecycle/antu.py` 58 %.

### Revisión del diff

`git --no-pager diff` + los cuatro archivos nuevos, revisados línea por línea
(`baseline/60_diff_revisado.txt`). Resumen: 4 archivos modificados (+96/−31 antes de retirar una
línea no usada) y 4 archivos nuevos. No se tocó: `VERSION`, `CHANGELOG.md`, `pyproject.toml`,
`README.md`, `PUBLIC_API.md`, `DATA_MODEL.md`, ni ningún esquema. No hay cambios accidentales,
ni código muerto, ni TODOs. Se retiró una asignación (`_base_unit_ids`) que había quedado sin
consumidor antes de cerrar el diff.

---

## E. Estado final

| dato | valor |
|---|---|
| HEAD final | `5fd8777a8305097792380fceb9ff861de208147a` — **sin cambios** |
| rama | `HEAD` (detached) |
| `git status --porcelain` final | 4 modificados + 5 no rastreados (ver abajo) |
| commits | **ninguno** |
| índice Git | **intacto** (no se usó `git add`, tampoco `-N`) |
| `VERSION` / `CHANGELOG.md` | sin tocar (0.2.0) |
| PyPI / tags / releases | **no** se publicó ni se creó nada |
| paquete instalado | **no** se instaló en ningún entorno |

### Archivos modificados (4)

```
 M src/kuyen/api/memory.py        # pasa declaración e ids de la base al validador
 M src/kuyen/backup/archive.py    # _reject_unsafe_target antes de tocar el destino
 M src/kuyen/lifecycle/antu.py    # _verify_proposal usa el validador canónico compartido
 M src/kuyen/storage/commit.py    # _require_expected_base + blobs dentro del lock
```

### Archivos nuevos (5)

```
?? src/kuyen/validation/canonical.py
?? tests/api/test_a1_canonical_validation.py
?? tests/storage/test_a2_stale_base_commit.py
?? tests/storage/test_a3_backup_target.py
?? docs/reports/KUYEN_PACKAGE_HARDENING_01_2026-11-01.md   (este informe)
```

### Confirmaciones explícitas

- **LeftraruOS no fue clonado, leído ni modificado** en esta ejecución; tampoco `leftraru-cl` ni
  `leftraru-lft`.
- **No se publicó nada**: ni PyPI, ni tag, ni release, ni despliegue.
- No se alteraron credenciales, DNS, permisos ni servicios externos. No se imprimió ningún secreto.
- El árbol `knowledge/kuyen` (0.1.9) quedó intacto.
- Todas las pruebas destructivas se ejecutaron en directorios desechables bajo `/tmp` o `tmp_path`,
  verificados antes de la llamada. No se tocó ningún store existente.

### Veredicto

**`PASS` para el alcance A1–A3.**

- A1, A2 y A3 fueron **reproducidos antes de corregir** (19 pruebas: 16 fallaban).
- Cada defecto tiene **pruebas de regresión** (23 en total) que pasan.
- Las correcciones son mínimas y **no cambian la superficie pública**: `KuyenMemory`, `build_document`
  y `kuyen.errors` conservan firmas y semántica para datos válidos; el cambio es *fail-closed* para
  datos inválidos, con la única decisión de contrato declarada en A1.
- La suite completa se ejecutó antes y después: 185→208 passed, 0 fallos, 2 skips preexistentes,
  cobertura 75 % en ambos extremos.
- `git apply` del parche sobre un checkout limpio de `5fd8777` reproduce el estado final y la suite
  pasa (210 pruebas, 0 fallos).
- M1 y M2 quedan **abiertos por diseño**, con diagnóstico reproducible y plan de pruebas.

### Siguiente paso recomendado (no ejecutado)

Construir el paquete candidato e instalarlo en un entorno aislado de LeftraruOS para validar el flujo
real de memoria. **Advertencia de acoplamiento para esa etapa:** hoy `leftraru-os` **no importa**
`kuyen` en ningún punto (cero ocurrencias de `import kuyen` / `from kuyen`); su memoria canónica es una
copia promovida (`runtime/memory_canonical`, contrato `RUNTIME_MEMORY_ADAPTER_1.0`) con una proyección
declarada como *lossy*. La etapa 3 debe decidir si **sustituye** ese adaptador por el paquete
instalado o **añade** una ruta nueva; sin esa decisión se corre el riesgo de operar dos memorias
canónicas en paralelo, que es exactamente lo que el criterio del runtime prohíbe.

KÜYEN **no ha sido validado como dependencia real de LeftraruOS** en esta ejecución.

---

## Entregables y evidencias

| entregable | ruta |
|---|---|
| informe | `docs/reports/KUYEN_PACKAGE_HARDENING_01_2026-11-01.md` (este archivo, no rastreado) |
| parche completo (modificados + nuevos) | `/tmp/kuyen_hardening_01/hardening.patch` (fuera del repositorio, para que no pueda commitearse por accidente) |
| pruebas de regresión | `tests/api/test_a1_canonical_validation.py`, `tests/storage/test_a2_stale_base_commit.py`, `tests/storage/test_a3_backup_target.py` |
| evidencia cruda | `/tmp/kuyen_hardening_01/baseline/` (suite antes/después, cobertura, reproducción, junit, diff revisado, diagnóstico M1/M2) |
| diagnóstico M1/M2 (script) | `/tmp/kuyen_hardening_01/diagnostics/m1_m2_diagnosis.py` |

El parche se verificó así: `git apply --check` + `git apply` sobre un `git worktree` limpio en
`5fd8777`, seguido de `PYTHONPATH=src python3 -m pytest` → 210 pruebas, 0 fallos. El worktree de
verificación se eliminó después.
