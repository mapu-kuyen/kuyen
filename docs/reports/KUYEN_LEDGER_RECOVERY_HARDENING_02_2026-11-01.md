# KUYEN_LEDGER_RECOVERY_HARDENING_02 — Informe de ejecución

**Paquete:** `kuyen` 0.2.0 · **Commit base:** `5fd8777a8305097792380fceb9ff861de208147a`
**Workspace:** `/tmp/kuyen_hardening_01/kuyen` (working tree con A1–A3 de `KUYEN_PACKAGE_HARDENING_01`)
**Fecha:** 2026-11-01 (UTC-3) · **Alcance:** M1 (concurrencia del ledger) y M2 (recuperación de escrituras incompletas)
**Veredicto:** **PASS** para M1 y M2 · sin empaquetado, publicación ni integración con LeftraruOS

---

## A. Identidad

| dato | valor |
|---|---|
| ruta | `/tmp/kuyen_hardening_01/kuyen` (clon de `https://github.com/mapu-kuyen/kuyen.git`) |
| HEAD | `5fd8777a8305097792380fceb9ff861de208147a` — **sin cambios al inicio y al final** |
| rama | `HEAD` (detached) |
| `VERSION` | `0.2.0` (sin cambios) |
| Python | 3.13.1 — `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3` |
| import | `kuyen.__file__` = `/private/tmp/kuyen_hardening_01/kuyen/src/kuyen/__init__.py` |
| entorno | `PYTHONPATH=src`; ninguna instalación; ninguna otra variable usada |
| estado Git inicial | 4 modificados + 5 no rastreados (A1–A3 y el informe previo), árbol **sin commitear** |
| artefactos previos | `docs/reports/KUYEN_PACKAGE_HARDENING_01_2026-11-01.md` y `/tmp/kuyen_hardening_01/hardening.patch` presentes |
| A1–A3 íntegros | `validate_canonical_objects` (3 archivos), `_require_expected_base`, `_reject_unsafe_target` y las 23 pruebas de A1–A3 presentes |

### Línea base reproducida

```
PYTHONPATH=src python3 -m pytest -q --junitxml=baseline_02/10_suite_before.xml
→ 210 recogidos · 208 passed · 0 failed · 0 errors · 2 skipped
cobertura: 75 % (7 628 sentencias)
```

Coincide con el resultado histórico de referencia. Los dos `skipped` son preexistentes.
No se hizo `checkout`, `reset`, `clean`, `rebase` ni `cherry-pick` en ningún momento.

---

## B. M1 — integridad del ledger ante escritores concurrentes

### Causa raíz

`lifecycle/ledger.py::append_event` ejecutaba una secuencia *read-then-append* sin exclusión:

1. `events(store)` lee y parsea todo el ledger → 2. `seq = len(chain) + 1` → 3. `prev =
chain[-1]["event_hash"]` (o `GENESIS`) → 4. construye el cuerpo → 5. `append_line(...)`.

`lifecycle/unit.py::record_revision` tenía el mismo patrón: lee `revisions`, decide y escribe el
registro + `unit/STATE.json`.

`storage/store.py::writer_lock()` **existía** (advisory `flock` sobre `locks/writer.lock`) pero sólo
lo usaban `commit_version` y `recover_pending`. Ni `execute_antu` ni `record_failed_antu` ni
`import_canonical` lo tomaban, así que dos escritores leían la misma cola antes de que ninguno
escribiera y publicaban el mismo `seq` y el mismo `prev_event_hash`.

Alcance real de `writer_lock` antes de este experimento: exclusión entre **descriptores**, por lo que
sí separa hilos (cada uno abre el suyo) y procesos, pero **no** era re-entrante: tomarlo dos veces en
el mismo hilo se bloqueaba contra sí mismo. Por eso no se podía simplemente envolver la operación.

### Reproducción (antes de corregir)

Ejecutada sobre `5fd8777 + hardening.patch` (A1–A3, sin M1/M2), con las pruebas nuevas copiadas:
**21 de 21 fallan**. Firma observada, idéntica a la auditoría anterior:

```
event N: unexpected seq M
event N: prev_event_hash does not link to the previous event
```

Las cinco rondas parametrizadas de hilos fallaron (5/5 corrupción), la ronda multiproceso falló y las
pruebas de M2 fallaron con `JSONDecodeError` / ausencia de `ledger_state`. Registro:
`baseline_02/20_reproduction_before_fix.log`.

### Diseño de exclusión aplicado

1. **`CanonicalStore.writer_lock()` re-entrante.** El `flock` se mantiene (exclusión real entre
   hilos y procesos), pero el anidamiento por hilo se resuelve con un `threading.local` que cuenta
   profundidad por *store resuelto*: la primera adquisición abre un descriptor y toma el `flock`, las
   siguientes del mismo hilo no abren otro. Sin esto, el `flock` (que es por *open file description*)
   se bloquearía contra el descriptor ya tomado por el mismo proceso.
2. **La operación completa es la unidad.** `_write_operation` envuelve `execute_antu`, `commit`,
   `record_failed_antu` e `import_canonical`: `next_revision` + `record_revision` + todos los
   `append_event` de una ejecución quedan dentro de la misma sección crítica.
3. **Los primitivos también se protegen solos.** `append_event` y `record_revision` toman el lock
   (re-entrante: gratis si el llamador ya lo tiene), de modo que un llamador directo tampoco puede
   corromper la cola.
4. **Sin cambios de formato ni de orden de escritura.** El sobre del evento conserva exactamente las
   mismas claves (`schema_name`, `schema_version`, `seq`, `event_type`, `prev_event_hash`, payload,
   `event_hash`) y `EVENT_TYPES` no se modificó.

### Alcance de concurrencia soportado

| modelo | soportado | mecanismo | verificado |
|---|---|---|---|
| hilos del mismo proceso | sí | `flock` sobre descriptores distintos + re-entrancia por hilo | Prueba A (6 escritores × 5 rondas) |
| procesos independientes | sí | `flock` entre procesos | Prueba B (4 procesos) |
| lectura concurrente | sí | los lectores no bloquean y toleran una cola truncada (M2) | Pruebas C de M2 |

Limitaciones declaradas: el paquete es POSIX (`fcntl`); `flock` no es fiable en algunos sistemas de
archivos de red, y ahí el lock sería advisory como ya declara `FORMAT.json`. No se probó en Windows
ni sobre NFS. `fork` mientras un hilo mantiene el lock no se probó (el estado de re-entrancia es por
proceso).

### Pruebas (archivo `tests/lifecycle/test_m1_ledger_concurrency.py` y `…_multiprocess.py`)

| prueba | diseño | resultado |
|---|---|---|
| **A — hilos** | `threading.Barrier(6)`, 5 rondas, cada escritor abre su propia `KuyenMemory` y ejecuta `record_failed_antu` | PASS: `seq` 1..N contiguos, `prev_event_hash` encadenado, revisiones `R0000..` únicas y contiguas, `verify().ok` |
| **A' — anidamiento** | el mismo hilo toma el lock dos veces y escribe | PASS: no hay autobloqueo |
| **B — procesos** | 4 intérpretes independientes sincronizados por un fichero “go” | PASS: 4 eventos, `seq` 1..4, cadena íntegra, 4 revisiones |
| **C — integridad posterior** | tras concurrencia: `verify()`, `backup()`, `restore()` en otro directorio | PASS: `verify_backup().ok`, la cadena restaurada es idéntica (seq, `event_hash`, `prev_event_hash`) y las revisiones coinciden |
| **D — interrupción** | `append_line` monkeypatcheado para escribir media línea y abortar | PASS: queda un registro incompleto, `ledger_state() == TRUNCATED_TAIL`, `verify()` en `ok=False`, el prefijo válido se sigue leyendo y la recuperación lo repara |

### Qué puede dejar una interrupción (comportamiento real medido)

Evidencia: `baseline_02/40_interruption_boundary.json`.

| escenario | resultado observado |
|---|---|
| corte durante el *append* del evento | **evento parcial**: media línea sin `\n` → clasificada `TRUNCATED_TAIL`, nunca contada como evento |
| corte entre el evento y la revisión de unidad | **evento completo sin historial**: el evento queda (2 eventos), la revisión no se crea (1 revisión); `verify().ok = True` porque la historia sigue contigua. La revisión faltante **no** se reconstruye desde el ledger (no es una promesa del contrato) |
| historial actualizado sin evento | no alcanzable por el orden de escritura (el evento se escribe antes de la revisión) |
| secuencia perdida | ya no ocurre entre escritores: la asignación de `seq` está dentro del lock |
| hash inconsistente | no: un corte produce una línea incompleta (truncada), no un evento con hash inválido |

---

## C. M2 — recuperación ante una línea truncada

### Causa raíz

`lifecycle/ledger.py::events()` parseaba **todas** las líneas con `json.loads` y era la base de
`append_event`, `last_event`, `events_for_antu`, `events_of_type`, `ledger_digest`, de la API
(`KuyenMemory.ledger()`) y de `recover_pending()` vía `events_of_type`. Una última línea cortada por
una escritura interrumpida lanzaba `JSONDecodeError` en **todas** ellas: la memoria quedaba no
legible y no escribible, no sólo no verificable. `read_tolerant()` ya existía (parsea sin lanzar y
reporta líneas dañadas) pero sólo lo usaba `verify_chain`.

### Política de recuperación implementada

`read_classified(store)` clasifica el ledger **sin lanzar nunca**:

| estado | condición | tratamiento |
|---|---|---|
| `INTACT` | todas las líneas parsean y el fichero termina en `\n` | nada |
| `TRUNCATED_TAIL` | la última porción no termina en `\n` y **no hay** daño previo | reparable |
| `CORRUPT` | cualquier línea completa no parsea (o hay daño previo + cola truncada) | **fail-closed**, sin reparación |

Sobre la cadena (estado independiente del parseo) `verify_chain()` sigue comprobando `seq`
contiguos, `prev_event_hash` enlazado y `event_hash` recalculado: eso cubre “registros completos con
secuencia incorrecta” y “cadena de hashes inconsistente”, que **no** se reparan automáticamente.

`repair_ledger(store)` sólo actúa sobre `TRUNCATED_TAIL`, bajo el lock y **sin descartar evidencia**:

1. copia los bytes originales intactos a `ledger/quarantine/<sha256>.jsonl` (nunca se sobrescribe);
2. escribe `ledger/recovery/REC-<id>.json` en estado `PREPARED` **antes** de tocar el fichero;
3. reescribe `ledger/antu.jsonl` quitando únicamente la porción incompleta — o completando el salto
   de línea cuando la porción final **sí** parsea (registro completo sin `\n`): en ese caso el
   registro se conserva y sólo se le añade el `\n`;
4. completa el registro con `events_after`/`head_after` y estado `COMPLETED`.

`recovery_id` es determinista (`sha256` de los bytes originales + hash de la cola + acción), de modo
que repetir la operación no crea artefactos nuevos. La cola incompleta **nunca** se presenta como
evento confirmado: no entra en `events()` ni en el recuento, y queda descrita (bytes, hash, línea y
preview) en el registro de recuperación.

### Integración en las APIs

| API | antes | ahora |
|---|---|---|
| `ledger()` | `JSONDecodeError` con cola truncada | devuelve el prefijo válido; `StoreError` si hay corrupción interna |
| `ledger_state()` | no existía | clasificación completa (estado, cola, problemas, registros de recuperación); nunca lanza, nunca repara |
| `pending()` / `history()` / `graph()` / `status()` | `JSONDecodeError` | funcionan con cola truncada |
| `execute_antu()` (y cualquier escritura) | `JSONDecodeError` | repara la cola truncada **antes** de escribir y continúa la cadena |
| `recover()` | `JSONDecodeError` | repara la cola y luego reanuda commits pendientes; `StoreError` si la corrupción no es reparable |
| `verify()` | reportaba la línea | reporta `ledger.state`, `ledger.tail` y `ledger.recovery` (incluye si hubo reparación); **sigue en `ok=False`** mientras haya cola truncada |

### Pruebas (archivo `tests/lifecycle/test_m2_ledger_recovery.py`)

| prueba | escenario | resultado |
|---|---|---|
| **A** | cola truncada añadida al final | PASS: `TRUNCATED_TAIL`, `verify().ok=False` con “incomplete record”, prefijo intacto |
| **C** | consultas con el ledger dañado | PASS: `ledger()`, `pending()`, `history()`, `current()`, `graph()` responden; `status()['integrity']['ok']` es `False` |
| **D** | `recover()` sobre cola truncada | PASS: repara; los N eventos válidos siguen ahí; cuarentena con los bytes exactos; registro `COMPLETED` con `events_before/after` |
| **B** | corrupción en la línea 2 | PASS: `CORRUPT`; `recover()` lanza `StoreError`; el fichero queda **byte a byte idéntico**; no se crean cuarentena ni registros |
| **B'** | corrupción intermedia **y** cola truncada | PASS: sigue siendo `CORRUPT` (no se confunde con una interrupción final) y el fichero no se toca |
| **E** | escritura posterior a la recuperación | PASS: `seq` continúa (N+1), `prev_event_hash` enlaza con la cabeza reparada, `verify()` distingue `recovery.repaired = True` de un ledger intacto |
| **E'** | registro final completo sin `\n` | PASS: se conserva el registro y sólo se completa el salto de línea (`COMPLETED_FINAL_NEWLINE`) |
| **F** | recuperación dos y tres veces | PASS: la segunda devuelve `repaired=False`; cuarentena, registros y fichero no cambian; sin eventos duplicados |

### Conservación del material original

La cuarentena es una copia **exacta** (mismos bytes, mismo `sha256`, nombre = hash) y el registro de
recuperación la referencia (`quarantine_file`, `original_sha256`, `original_bytes`,
`incomplete_bytes`, `incomplete_sha256`, `incomplete_preview`). Nada se borra del material original y
el evento incompleto no se reinterpreta como evento válido.

---

## D. Validación combinada (M1 + M2)

Archivo: `tests/lifecycle/test_m1_m2_combined.py` (2 pruebas, ambas PASS).

Secuencia del escenario principal:

1. **Concurrencia**: 4 hilos con `Barrier` escriben desde el mismo estado → 4 eventos, cadena íntegra.
2. **Interrupción controlada**: `append_line` corta a mitad de línea → `TRUNCATED_TAIL`; el prefijo
   válido queda idéntico (`memory.ledger() == before_cut`).
3. **Recuperación**: repara y conserva los 4 eventos; `verify().ok = True`.
4. **Segunda ronda concurrente** de 4 hilos → 8 eventos; los `antu_id` de la primera ronda siguen ahí.
5. **Backup y restore** en otro directorio → `verify()` del restaurado en `ok`, cadena restaurada
   idéntica (`seq`, `event_hash`) y `recovery.repaired = True` también en el restaurado (el registro
   de recuperación viaja con el backup).
6. **Nueva escritura** tras todo lo anterior → `seq = baseline + 1`, enlace correcto.
7. **Segunda recuperación** → `repaired = False`, mismos artefactos, sin duplicados.

El escenario secundario intercala una recuperación **entre** dos rondas concurrentes y comprueba que
las revisiones de unidad siguen contiguas y únicas (`R0000…`).

Integridad comprobada en cada paso: `seq` contiguos, `prev_event_hash` encadenado, `event_hash`
recalculado por `verify_chain`, `event_hash` únicos y correspondencia evento ↔ revisión.

### Compatibilidad con stores existentes

Evidencia: `baseline_02/41_store_compatibility.json`.

Se creó un store con el código **anterior** (`5fd8777` + A1–A3, sin M1/M2): 1 versión, 7 eventos,
4 revisiones. Se abrió con el código nuevo: `ledger_state() == INTACT`, `verify().ok = True`, sin
artefactos de recuperación, y una escritura nueva continuó la cadena (`seq = 8`,
`prev_event_hash` = cabeza antigua, `verify().ok = True`). No hay migración, ni cambio de formato, ni
incompatibilidad: los directorios `ledger/quarantine` y `ledger/recovery` sólo aparecen cuando hay
una reparación.

---

## E. Suite

| momento | recogidos | passed | failed | errors | skipped | cobertura |
|---|---|---|---|---|---|---|
| antes | 210 | 208 | 0 | 0 | 2 | **75 %** (7 628 sentencias) |
| después | **231** | **229** | **0** | **0** | **2** | **75 %** (7 757 sentencias) |
| antes de corregir (reproducción) | 21 | 0 | **21** | 0 | 0 | — |

- Pruebas nuevas: **21** (8 M1-hilos/integridad/interrupción, 1 multiproceso, 10 M2, 2 combinadas).
- No se añadió ningún `xfail` ni `skip`; los 2 `skipped` son los preexistentes.
- No se debilitó `verify()`: con cola truncada o corrupción sigue devolviendo `ok = False`.
- Estabilidad: 5 ejecuciones consecutivas de las pruebas de concurrencia y combinadas → todas verdes.
- Cobertura por archivo tocado: `lifecycle/ledger.py` 90 %, `storage/store.py` 87 %,
  `lifecycle/unit.py` 89 %, `api/memory.py` 92 %.
- Comandos usados:

```bash
PYTHONPATH=src python3 -m pytest -q
PYTHONPATH=src python3 -m pytest -q --junitxml=baseline_02/30_suite_after.xml
PYTHONPATH=src python3 -m pytest -q -p no:cacheprovider --cov=kuyen --cov-report=term
PYTHONPATH=src python3 -m pytest tests/lifecycle/test_m1_ledger_concurrency.py \
    tests/lifecycle/test_m1_m2_combined.py tests/lifecycle/test_m1_ledger_multiprocess.py -q   # ×5
```

---

## F. Revisión final

### Archivos modificados

| archivo | cambio |
|---|---|
| `src/kuyen/storage/store.py` | `writer_lock()` pasa a ser **re-entrante por hilo** (thread-local por store) manteniendo el `flock` entre hilos y procesos (+30/−1) |
| `src/kuyen/lifecycle/ledger.py` | `read_classified`, `repair_ledger`, `recovery_records`, `quarantine_dir`, `recovery_dir`; `events()` tolerante a cola truncada y fail-closed ante corrupción; `append_event` bajo lock y reparando antes de escribir; `verify_chain` reporta estado, cola y reparaciones (+235/−37) |
| `src/kuyen/lifecycle/unit.py` | `record_revision` toma el lock (append + `STATE.json` como una operación); cuerpo movido a `_record_revision_locked` (+14) |
| `src/kuyen/api/memory.py` | `_write_operation` en `execute_antu`, `commit`, `record_failed_antu`, `import_canonical`; `ledger_state()` nuevo; `verify()` reporta `ledger`; `recover()` repara la cola antes de reanudar (+57/−6, incluye el cambio de A1 en la llamada a `_verify_proposal`) |

### Archivos nuevos

```
tests/lifecycle/test_m1_ledger_concurrency.py    (8 pruebas)
tests/lifecycle/test_m1_ledger_multiprocess.py   (1 prueba)
tests/lifecycle/test_m2_ledger_recovery.py       (10 pruebas)
tests/lifecycle/test_m1_m2_combined.py           (2 pruebas)
docs/reports/KUYEN_LEDGER_RECOVERY_HARDENING_02_2026-11-01.md
```

No se tocó: `VERSION` (0.2.0), `CHANGELOG.md`, `pyproject.toml`, esquemas, `FORMAT.json`, ni el sobre
de los eventos. A1–A3 no se modificaron salvo lo imprescindible: la única línea compartida es la
llamada a `_verify_proposal` dentro de `execute_antu`, que ya existía.

### Riesgos abiertos (declarados, no ocultados)

1. **`flock` en sistemas de archivos de red** (NFS/SMB) puede no ser fiable; el propio `FORMAT.json`
   declara el modelo como *advisory*. No se probó en red ni en Windows (el paquete usa `fcntl`).
2. **Un evento sin su revisión de unidad** es posible si el proceso muere entre ambos (`record_failed_antu`
   y `execute_antu` escriben primero el evento). El ledger queda verifiable y la historia contigua, pero
   la revisión no se reconstruye desde el ledger. Si se quisiera equivalencia estricta habría que
   escribir la revisión primero o reconstruirla en `recover()`: es una decisión de contrato, no un bug.
3. **`project()`/outbox** siguen escribiendo su registro fuera del lock de operación (sólo el evento
   va protegido). No es parte de M1 y no se amplió el alcance.
4. **`write_atomic` usa un nombre temporal basado en PID**; dos hilos del mismo proceso que escriban el
   mismo destino a la vez colisionan. Con M1 las escrituras del ledger y del historial van bajo lock, y
   los blobs del commit ya se movieron dentro del lock en A2, pero el primitivo sigue siendo frágil si
   se usa concurrentemente fuera de esos caminos.
5. La reparación **no** valida la semántica de la cola: sólo distingue “incompleta al final” de
   “corrupta”. Una cola truncada que casualmente parseara se conservaría completando el `\n`.

### Compatibilidad con stores existentes

Sin migración: mismos eventos, mismo `FORMAT.json`, mismos directorios. Los directorios de cuarentena y
recuperación son aditivos y sólo existen si hubo reparación. Verificado abriendo un store creado con el
código anterior y continuando su cadena (sección D).

### Estado Git final

```
HEAD  5fd8777a8305097792380fceb9ff861de208147a   (sin cambios, sin commits)
 M src/kuyen/api/memory.py
 M src/kuyen/backup/archive.py        (A1–A3, experimento 01)
 M src/kuyen/lifecycle/antu.py        (A1–A3, experimento 01)
 M src/kuyen/lifecycle/ledger.py      (M2, este experimento)
 M src/kuyen/lifecycle/unit.py        (M1, este experimento)
 M src/kuyen/storage/commit.py        (A2, experimento 01)
 M src/kuyen/storage/store.py         (M1, este experimento)
?? docs/  src/kuyen/validation/canonical.py  tests/...  (A1–A3 + M1/M2)
```

Índice Git intacto (no se usó `git add`, tampoco `-N`). `VERSION` sin tocar. Nada publicado ni instalado.
LeftraruOS, `leftraru-cl`, `leftraru-lft` y el árbol 0.1.9 no se tocaron.

### Veredicto

**`PASS`.**

- M1 corregido y verificado para los dos modelos declarados como soportados: **hilos** (barrera, 5
  rondas, 6 escritores) y **procesos** (4 intérpretes independientes). `seq` únicos y contiguos, cadena
  de hashes íntegra, 0 corrupciones en las rondas de prueba (antes: 5/5 rondas corruptas).
- M2 recuperable **sólo** cuando la corrupción es una truncación final; la corrupción intermedia se
  detecta y **no** se repara ni se toca el fichero; el material original se conserva en cuarentena; la
  recuperación es idempotente y la escritura posterior continúa la cadena.
- Suite completa sin regresiones (231 recogidos, 0 fallos) y cobertura sostenida (75 %).

### Siguiente paso recomendado (no ejecutado)

Cerrar los hallazgos restantes que afectan garantías del paquete (M3 detección de manipulación, M5 Antü
mal formado frente a `commit`, M6 escalabilidad del commit, B1 `recover_pending`, B2 restore sobre
directorio existente) y, sólo después, construir el candidato instalable para validarlo desde
LeftraruOS. La decisión de acoplamiento con `runtime/memory_canonical` sigue pendiente y pertenece a esa
etapa.

---

## Entregables

| entregable | ruta |
|---|---|
| este informe | `docs/reports/KUYEN_LEDGER_RECOVERY_HARDENING_02_2026-11-01.md` (no rastreado) |
| parche incremental | `/tmp/kuyen_hardening_01/ledger_recovery_hardening_02.patch` |
| parche del experimento 01 (intacto) | `/tmp/kuyen_hardening_01/hardening.patch` |
| evidencia | `/tmp/kuyen_hardening_01/baseline_02/` (suite, cobertura, reproducción, junit, compatibilidad, frontera de interrupción) y `/tmp/kuyen_hardening_01/diagnostics/` |
