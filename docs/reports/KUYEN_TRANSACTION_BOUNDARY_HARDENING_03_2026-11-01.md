# KUYEN_TRANSACTION_BOUNDARY_HARDENING_03 — Informe de ejecución

**Paquete:** `kuyen` 0.2.0 · **Commit base:** `5fd8777a8305097792380fceb9ff861de208147a`
**Workspace:** `/tmp/kuyen_hardening_01/kuyen` (working tree con A1–A3 y M1–M2 de los experimentos 01 y 02)
**Fecha:** 2026-11-01 (UTC-3)
**Veredicto:** **PASS** para los tres frentes · sin empaquetado, publicación ni integración con LeftraruOS

---

## A. Identidad y estado

| dato | valor |
|---|---|
| ruta | `/tmp/kuyen_hardening_01/kuyen` |
| HEAD | `5fd8777a8305097792380fceb9ff861de208147a` — **sin cambios al inicio y al final** |
| rama | `HEAD` (detached) |
| `VERSION` | `0.2.0` (sin tocar) |
| Python | 3.13.1 · `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3` |
| import | `kuyen.__file__` = `/private/tmp/kuyen_hardening_01/kuyen/src/kuyen/__init__.py` |
| entorno | `PYTHONPATH=src`; sin instalaciones; sin otras variables |
| estado Git inicial | 7 modificados + 9 no rastreados (A1–A3 + M1–M2, ambos informes) |
| estado Git final | **10 modificados** (se añaden `canonical.py`, `projection/native.py` y `projection/outbox.py`) + **13 entradas no rastreadas / 20 archivos** (se añaden el informe 03, 4 archivos de prueba y `projection_helpers.py`) |
| commits / índice | **ninguno** / intacto (no se usó `git add`) |

### Artefactos previos (hashes registrados al inicio y al final)

| artefacto | sha256 |
|---|---|
| `hardening.patch` (01) | `6ce8914303c77e73391f21991ed8e228bd85fc91e52bf275526e0bcd90ce3d33` |
| `ledger_recovery_hardening_02.patch` (02) | `67bc04b2f619067f6e5c794b8cde980c2ab1f01738e548698b69abb196bbdade` |
| `docs/reports/KUYEN_PACKAGE_HARDENING_01_2026-11-01.md` | presente, sin sobrescribir |
| `docs/reports/KUYEN_LEDGER_RECOVERY_HARDENING_02_2026-11-01.md` | presente, sin sobrescribir |

Correcciones previas verificadas como presentes: `validate_canonical_objects` (A1),
`_require_expected_base` (A2), `_reject_unsafe_target` (A3), `_write_operation` (M1),
`read_classified`/`repair_ledger` (M2), `_WRITER_SCOPES` (M1).

### Línea base reproducida

```
PYTHONPATH=src python3 -m pytest -q --junitxml=baseline_03/10_suite_before.xml
→ 231 recogidos · 229 passed · 0 failed · 0 errors · 2 skipped · cobertura 75 % (7 757 sentencias)
```

Coincide con la referencia del experimento 02. Los 2 `skipped` son los preexistentes
(integración real con OpenViking, `KUYEN_RUN_OPENVIKING` sin definir).

---

## Mapa de las operaciones de escritura

Inspección de todos los caminos que escriben y del límite que los cubre.

| operación lógica | escribe | exclusión **antes** | exclusión **ahora** |
|---|---|---|---|
| `execute_antu` | ledger `ANTU_RECEIVED` / `ANTU_REJECTED` / `ANTU_NO_SEMANTIC_CHANGE` | `writer_lock` (M1) | igual |
| `commit` → `commit_version` | objetos, manifiesto, índice, `CURRENT`, eventos `ANTU_COMPLETED`/`VERSION_COMMITTED`/`PROJECTION_ENQUEUED`, outbox, revisión | `writer_lock` (M1/A2) | igual |
| `record_failed_antu` | ledger + revisión | `writer_lock` (M1) | igual |
| `import_canonical` | igual que `commit` | `writer_lock` (M1) | igual |
| `backup` | copia fuera del store + evento `BACKUP_CREATED` | evento bajo `writer_lock`; la copia no muta el store | igual |
| `enqueue_projection` → `outbox.enqueue` | fichero de outbox nuevo | **ninguna** (check + write separados) | `writer_lock` |
| `project` → `native.project` | outbox (`IN_PROGRESS`, intentos, `DONE`), registro de proyección, evento `PROJECTION_COMPLETED` | **ninguna** | `claim` bajo lock + finalización bajo lock |
| `recover` | ledger reparado, commits pendientes, outbox, historial | `writer_lock` (M2) | + `release_interrupted` y `reconcile_unit_history` bajo lock |

Distinción que el código mantiene explícita (y el informe usa sin mezclarla):

1. **Publicar el estado canónico** = `commit_version` (manifiesto + índice + `CURRENT`).
2. **Registrar que debe proyectarse** = `PROJECTION_ENQUEUED` + operación de outbox.
3. **Ejecutar la proyección** = escritura en el motor externo (fuera de lock, es I/O).
4. **Confirmar que la proyección terminó** = registro + evento + `DONE` (una sola sección crítica).

La proyección **nunca** modifica la verdad canónica: se verificó comparando `current()`,
`versions()`, `graph()` e `history()` antes y después (prueba
`test_projection_never_modifies_canonical_truth`).

---

## B. Frente 1 — `project()` y outbox fuera del lock

### Causa raíz

`native.project` leía la operación, comprobaba sólo `status == DONE` y escribía `IN_PROGRESS`
sin exclusión. `KuyenMemory.project` recorría el outbox y llamaba a `run_projection` sin lock;
el evento `PROJECTION_COMPLETED` lo añadía la API **después** de que `run_projection` hubiera
escrito el registro y el `DONE`. Con dos ejecutores:

- ambos ejecutaban la misma operación (trabajo externo duplicado),
- ambos escribían el registro y el outbox (colisión de temporales incluida),
- se registraban **dos** eventos `PROJECTION_COMPLETED` y **dos** intentos.

Además, `DONE` y el evento eran dos escrituras separadas: un corte entre ambas dejaba una
proyección «completada» sin su evento, y un corte entre el registro y `DONE` dejaba el
registro sin estado.

### Reproducción antes de corregir (3 pruebas, todas fallaban)

| prueba | síntoma observado |
|---|---|
| dos ejecutores concurrentes | `FileNotFoundError` sobre `.tmp-proj-…json-<pid>` (temporal compartido) y, sin el fallo, dos eventos e intentos |
| operación `IN_PROGRESS` | el segundo ejecutor la ejecutaba y la marcaba `DONE` |
| `recover()` | no había forma de liberar una operación retenida (`KeyError: 'projections'`) |

### Corrección aplicada

1. **`outbox.claim(store, key)`** — lee el estado y escribe `IN_PROGRESS` dentro del
   `writer_lock`: sólo `PENDING`/`FAILED` son reclamables. Si otro ejecutor la tiene o ya está
   `DONE`, devuelve `None` y el llamador la salta (`project()` informa `skipped`).
2. **`outbox.release_interrupted(store)`** — durante `recover()`, toda operación `IN_PROGRESS`
   vuelve a `PENDING` registrando el intento `RELEASED_AFTER_INTERRUPTION`. Es idempotente.
3. **Finalización atómica** en `native.project`: registro + evento + `DONE` en una única
   sección crítica, con el evento escrito **antes** del `DONE` y deduplicado por
   `projection_id` (`record_completion_event`). Así `DONE` implica siempre registro y evento.
4. **`enqueue` y `update` bajo el lock** (check-y-escribe y read-modify-write del outbox).

El trabajo externo (escritura en OpenViking) sigue **fuera** del lock: no se serializa I/O lento,
se serializa la propiedad de la operación.

### Pruebas (7) y resultado

- dos hilos concurrentes → **1** proyección, **1** evento, **1** intento, `DONE`;
- operación `IN_PROGRESS` → no se roba (0 escrituras en el motor, 0 eventos);
- `recover()` libera y el reintento completa exactamente una vez;
- segunda recuperación → `released == []` (idempotente);
- `DONE` ⇒ registro + evento con el mismo `projection_id`;
- la proyección no altera la verdad canónica;
- proyección fallida → `FAILED` sin registro ni evento, y reintentable.

Además, **dos procesos** independientes que proyectan la misma operación: exactamente uno la
ejecuta (`1 0` / `0 1` en la salida de los hijos), 1 registro, 1 evento, 1 intento.

---

## C. Frente 2 — temporales de `write_atomic`

### Causa raíz

`write_atomic` construía el temporal como `.tmp-{nombre}-{pid}`. El PID es **el mismo para
todos los hilos del proceso**, así que dos hilos que escriben el mismo destino comparten un
único temporal:

- el segundo `open("wb")` **trunca** el archivo que el primero está escribiendo,
- el `os.replace` de uno **mueve** el temporal mientras el otro lo sigue escribiendo,
- el perdedor falla con `FileNotFoundError` al hacer `chmod`/`replace` sobre un temporal que ya
  no existe, y el destino puede quedar **truncado**.

Entre procesos el sufijo de PID hacía que no colisionaran (por accidente); el defecto era
interno al proceso. Además, una escritura fallida dejaba el temporal huérfano, y un temporal
abandonado de una ejecución anterior con el mismo PID se **reutilizaba en silencio**.

### Reproducción antes de corregir (3 de 6 pruebas fallaban)

| prueba | síntoma |
|---|---|
| dos hilos, mismo destino (12 rondas) | `FileNotFoundError: …/.tmp-shared.bin-<pid>` en la ronda 0 |
| temporal abandonado | el temporal previo era consumido y desaparecía (reutilización silenciosa) |
| interrupción antes del reemplazo | quedaba `.tmp-target.json-<pid>` en el directorio |

Las otras tres (destinos distintos, dos procesos, interrupción después del reemplazo) pasaban
y se conservan como guardas de no regresión.

### Corrección aplicada

`temporary_name(target)` → `.tmp-{nombre}-{pid}-{contador:x}-{urandom(4).hex()}`:
único por escritor dentro del proceso y distinto entre procesos. Se mantiene la publicación
atómica (`fsync` + `chmod` + **un** `os.replace` + `fsync` del directorio) y se añade limpieza
del propio temporal si la escritura falla, para que nunca quede un residuo que pueda
confundirse con un resultado.

Decisión declarada: un temporal **ajeno** o abandonado no se borra (podría pertenecer a otro
escritor vivo) y no se lee nunca; queda inerte. No se añadió un barrido automático porque sería
una política nueva y podría destruir trabajo en curso.

### Pruebas (6) y resultado

dos hilos mismo destino × 12 rondas (contenido exacto de **uno** de los dos, sin mezcla, sin
restos) · dos hilos destinos distintos · dos procesos mismo destino · temporal abandonado
inerte · interrupción antes del reemplazo (destino intacto, sin temporal) · interrupción
después del reemplazo (archivo completo publicado). **6/6 PASS.**

---

## D. Frente 3 — evento sin revisión tras una interrupción

### Inspección semántica del orden real

```
execute_antu   → ANTU_RECEIVED                     (la instrucción llegó)
               → ANTU_REJECTED | ANTU_NO_SEMANTIC_CHANGE (según validación / VERIFY_ONLY)
commit         → [objetos, manifiesto, índice]     (publicación)
               → ANTU_COMPLETED
               → PROJECTION_ENQUEUED
               → VERSION_COMMITTED
               → record_revision(COMPLETED)       (historial de la unidad)
```

`ANTU_COMPLETED` **no** significa que la operación lógica terminó: marca que el commit se
completó en el ledger. La revisión de unidad es el registro que ata la operación al historial
de la unidad (`output_version_id`, `input_version_id`, `canonical_graph_hash`) y es la que
`verify_unit_history()` usa para comprobar continuidad.

Respuestas a las preguntas de la sección 5.2:

| pregunta | respuesta verificada |
|---|---|
| ¿`ANTU_COMPLETED` significa que la operación terminó? | No: significa que la fase de commit terminó; el historial se escribe después. |
| ¿La revisión es obligatoria? | Sí para considerar la operación completa: sin ella el historial no cubre la versión publicada. |
| ¿Puede existir un evento sin revisión por diseño? | Podía ocurrir por interrupción y **no estaba representado**; ahora es un estado explícito. |
| ¿Cómo distingue el runtime una operación completa de una interrumpida? | `pending()["unreconciled"]` y `verify()["unit_history"]["unreconciled"]`. |
| ¿Existe estructura de estado pendiente? | No existía; `uncovered_versions()` la deriva de los manifiestos publicados. |
| ¿`recover()` puede detectarlo? | Antes no; ahora lo detecta y lo reconstruye con procedencia. |
| ¿La reconstrucción crea versión o altera una anterior? | No: sólo **añade** una revisión al final y un evento `RECONCILIATION`; no toca manifiestos ni historial previo. |

### Política adoptada (sin inventar semántica de eventos)

1. **Ninguna operación incompleta aparece como completa**: `verify()` incluye el problema
   `published version <id> has no unit revision (interrupted operation)` y devuelve `ok=False`;
   `pending()` la lista en `unreconciled`. No se debilitó `verify()`: se lo hizo más estricto.
2. **La evidencia se conserva**: la versión publicada, sus manifiestos, el ledger y las
   revisiones previas quedan intactos.
3. **Reconstrucción con procedencia**: `reconcile_unit_history()` deriva la revisión del
   **manifiesto publicado** (la autoridad canónica) y la registra con
   `detail.recovered = True`, `reason = PUBLISHED_VERSION_WITHOUT_REVISION`,
   `manifest_unit_revision`, `assigned_unit_revision` y `recovered_from`, más un evento
   `RECONCILIATION` (tipo ya existente, sin eventos nuevos).
4. **Idempotente**: una versión cubierta deja de ser «no cubierta»; la segunda recuperación no
   escribe nada.
5. **Sin duplicar revisiones**: usa `next_revision()` (el siguiente id libre) y `record_revision`
   deduplica por id; si el id que el manifiesto había reservado ya está tomado, la divergencia
   queda registrada en `manifest_unit_revision` vs `assigned_unit_revision`.

### Reproducción y pruebas (6)

Antes de corregir, **6/6 fallaban**: `verify()` devolvía `ok=True`, `pending()` no lo reportaba
y `recover()` no hacía nada.

| prueba | resultado |
|---|---|
| versión publicada sin revisión → reportada | PASS: `unreconciled` en `pending()` y en `verify()`, `ok=False` |
| operación completa → no reportada | PASS (guarda) |
| `recover()` reconstruye con procedencia | PASS: revisión `COMPLETED`, `detail.recovered`, evento `RECONCILIATION`, historial 2 revisiones sin duplicar |
| recuperación idempotente | PASS: segunda pasada no escribe revisión ni evento |
| nueva operación después de recuperar | PASS: historial contiguo `R0000..`, `verify().ok` |
| consulta desde una instancia nueva | PASS: `status()["integrity"]["ok"] is False` y `unit_history.unreconciled` visible |

---

## E. Validación combinada

Archivo: `tests/projection/test_combined_boundaries.py` (2 pruebas, ambas PASS).

Secuencia del escenario integrado:

1. store temporal con una versión canónica importada (1 operación de outbox).
2. **4 hilos** escriben a la vez (eventos + revisiones).
3. **interrupción controlada de un commit** antes de su revisión → versión publicada,
   `pending().unreconciled` la lista y `verify().ok` es `False`.
4. **interrupción de una proyección**: la operación queda `IN_PROGRESS` (ejecutor muerto).
5. `recover()` → libera la proyección, reconstruye la revisión y deja el ledger íntegro.
6. proyección de todas las versiones pendientes, y **4 hilos** más de escritura canónica.
7. ledger: `seq` 1..N contiguos y `prev_event_hash` encadenado; `verify().ok`.
8. `backup()` y `verify_backup()`.
9. `restore()` en otro directorio.
10. el restaurado conserva: `current()`, `versions()`, `ledger()` (idéntico), `history()`,
    `projections()` (mismos `projection_id`), `outbox.stats` y `verify().ok`; `reconcile()`
    no muestra la versión actual en `PROJECTION_PENDING` ni `PROJECTION_MISSING`.

Segunda prueba: **dos procesos** proyectan la misma operación a la vez → exactamente uno la
Ejecuta, 1 registro, 1 evento, 1 intento, `DONE`.

---

## F. Suite, cobertura y revisión

| momento | recogidos | passed | failed | errors | skipped | cobertura |
|---|---|---|---|---|---|---|
| antes | 231 | 229 | 0 | 0 | 2 | **75 %** (7 757 sentencias) |
| después | **252** | **250** | **0** | **0** | **2** | **77 %** (7 829 sentencias) |
| antes de corregir (reproducción) | 21 | 7 | **14** | 0 | 0 | — |

- Pruebas nuevas: **21** (6 de `write_atomic`, 7 de proyección/outbox, 2 combinadas, 6 del
  límite de operación).
- Sin `skip` ni `xfail` añadidos; los 2 `skipped` son los preexistentes.
- Estabilidad: 5 ejecuciones consecutivas de las pruebas de concurrencia, proyección y
  combinadas → todas verdes.
- Cobertura por archivo tocado: `projection/outbox.py` 94 %, `projection/native.py` 92 %,
  `lifecycle/unit.py` 92 %, `canonical.py` 89 %, `api/memory.py` 96 %. Antes de esta ejecución
  el camino de proyección **no tenía ninguna prueba**.

### Archivos modificados

| archivo | cambio |
|---|---|
| `src/kuyen/canonical.py` | `temporary_name()` único por escritor + limpieza del temporal propio si falla la escritura |
| `src/kuyen/projection/outbox.py` | `claim()`, `release_interrupted()`, `enqueue()` y `update()` bajo el `writer_lock` |
| `src/kuyen/projection/native.py` | `project()` reclama antes de trabajar y devuelve `None` si no puede; finalización (registro + evento + `DONE`) en una sección crítica; `record_completion_event()` |
| `src/kuyen/lifecycle/unit.py` | `published_versions()`, `uncovered_versions()`, `verify_unit_history()` reporta versiones sin revisión, `reconcile_unit_history()` reconstruye con procedencia |
| `src/kuyen/api/memory.py` | `project()` no duplica el evento y salta operaciones no reclamadas; `pending()` añade `unreconciled`; `verify()` añade `unit_history`; `recover()` libera proyecciones y concilia el historial |

### Archivos nuevos

```
tests/projection_helpers.py                        (motor falso compartido por las pruebas)
tests/storage/test_atomic_write_boundary.py        (6 pruebas)
tests/projection/test_projection_boundary.py       (7 pruebas)
tests/projection/test_combined_boundaries.py       (2 pruebas)
tests/lifecycle/test_operation_boundary.py         (6 pruebas)
docs/reports/KUYEN_TRANSACTION_BOUNDARY_HARDENING_03_2026-11-01.md
```

No se tocó `VERSION`, `CHANGELOG.md`, `pyproject.toml`, esquemas, `FORMAT.json` ni el sobre de
los eventos. A1–A3 y M1–M2 no se modificaron; los únicos cambios en archivos que ya habían
sido tocados son aditivos y se apoyan en la re-entrancia del lock introducida en M1.

### Riesgos que permanecen (declarados)

1. **`RECONCILIATION` como evento de reparación**: se reutiliza un tipo existente; no se añadió
   ningún evento nuevo, pero un consumidor que asuma que `RECONCILIATION` sólo proviene de
   `reconcile()` debe leer `reason` (aquí `PUBLISHED_VERSION_WITHOUT_REVISION`).
2. **Temporales ajenos**: no se borran nunca; un directorio con restos acumula basura inerte
   hasta que exista una tarea de mantenimiento explícita.
3. **Proyección concurrente con `restore`**: `restore` construye un store nuevo; nadie proyecta
   durante la restauración, pero no hay coordinación entre procesos sobre backups.
4. **`project()` mantiene el lock durante la finalización**, no durante la escritura externa: si
   el motor externo tarda, el lock se toma y se suelta (no se serializa el I/O).
5. **Un evento sin revisión sigue siendo posible** si el proceso muere entre ambas escrituras;
   lo que cambia es que ahora es **detectable, verificable y reparable con procedencia**.

---

## G. Semántica final de una operación

| estado | cómo se reconoce | qué garantiza |
|---|---|---|
| **COMPLETA** | versión publicada + revisión que la cubre + `VERSION_COMMITTED` | `verify().ok`, `pending().unreconciled == []` |
| **PENDIENTE / INTERRUMPIDA** | `pending()["incomplete"]`, `pending()["staging"]`, `pending()["unreconciled"]`, `unit_history.unreconciled` | `verify().ok = False`; `recover()` la completa o la libera |
| **PROYECCIÓN EN CURSO** | operación `IN_PROGRESS` en el outbox | no se puede reclamar; `recover()` la libera; no hay registro ni evento hasta finalizar |
| **PROYECCIÓN COMPLETA** | `DONE` + registro + evento `PROJECTION_COMPLETED` (mismo `projection_id`) | los tres existen siempre juntos |
| **PROYECCIÓN FALLIDA** | `FAILED` + intento con `error` | reclamable de nuevo; sin registro ni evento |

---

## H. Veredicto

**`PASS`.**

- Las escrituras de proyección y outbox respetan un límite explícito: reclamación atómica,
  finalización atómica, `enqueue`/`update` bajo lock, y el I/O externo fuera del lock.
- No quedan colisiones de temporales entre escritores soportados (hilos y procesos), y una
  escritura fallida no deja residuos propios.
- Una interrupción ya no deja una operación presentada engañosamente como completa: `verify()`
  lo reporta, `pending()` lo lista y `recover()` lo repara con procedencia.
- La recuperación es idempotente; no se pierden eventos ni revisiones confirmadas.
- `verify()` refleja el estado real y es **más** estricto que antes, no menos.
- Backup y restore conservan las garantías anteriores y añaden la coherencia de proyecciones
  (verificada en la prueba combinada).
- A1–A3 y M1–M2 siguen pasando (252 pruebas, 0 fallos).

Riesgos 1–5 de la sección F: ninguno impide el veredicto; todos están acotados y documentados.

### Siguiente paso recomendado (no ejecutado)

Cerrar los hallazgos restantes de garantías (M3 detección de manipulación, M5 Antü mal formado
frente a `commit`, M6 escalabilidad del commit, B1 `recover_pending`, B2 restore sobre directorio
existente) y sólo después construir el candidato instalable para validarlo desde LeftraruOS. La
decisión de acoplamiento con `runtime/memory_canonical` sigue pendiente y pertenece a esa etapa.

---

## Entregables

| entregable | ruta |
|---|---|
| este informe | `docs/reports/KUYEN_TRANSACTION_BOUNDARY_HARDENING_03_2026-11-01.md` (no rastreado) |
| parche incremental | `/tmp/kuyen_hardening_01/transaction_boundary_hardening_03.patch` |
| parches anteriores (intactos) | `/tmp/kuyen_hardening_01/hardening.patch`, `/tmp/kuyen_hardening_01/ledger_recovery_hardening_02.patch` |
| evidencia | `/tmp/kuyen_hardening_01/baseline_03/` (suite antes/después, cobertura, reproducción sin el fix, junit) |
