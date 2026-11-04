# KÜYEN — release candidate 0.2.1rc1 (KUYEN_RELEASE_CANDIDATE_05)

**Fecha:** 2026-11-02 · **Workspace:** `/tmp/kuyen_hardening_01/kuyen` · **Commit base:**
`5fd8777a8305097792380fceb9ff861de208147a` · **Versión del candidato:** `0.2.1rc1`
· **Estado:** candidato construido, instalado y probado; **no publicado**.

```
VEREDICTO: RELEASE_CANDIDATE_PASS
```

Todos los criterios de aceptación se han demostrado sobre los artefactos reales: M6 cerrado
con mediciones antes/después, B1 y B2 reproducidos y corregidos con recuperación idempotente,
M7 y B5 corregidos y verificados en entornos limpios, wheel y sdist construidos, instalados
en dos entornos independientes y sometidos al mismo flujo funcional con **resultados
idénticos**. Nada se ha publicado, etiquetado ni subido, y ningún repositorio ajeno se ha
tocado.

---

## A. Alcance ejecutado

| fase | contenido | resultado |
|---|---|---|
| 0 | verificación de la línea base acumulada (identidad, hashes, correcciones, suite) | coincide con el informe 04 |
| 1 | M6 — escalabilidad del commit y del ledger | medido, corregido, re-medido |
| 2 | B1 — clasificación de staging en `recover_pending` | reproducido, corregido, 8 pruebas |
| 3 | B2 — restauración sobre directorio existente | reproducido, corregido, 12 pruebas |
| 4 | M7 — extra `[dev]` | reproducido, corregido, verificado en entorno limpio |
| 5 | B5 — mínimo de `setuptools` | reproducido, mínimo real determinado (77.0.1), verificado |
| 6 | identidad de versión y construcción | `0.2.1rc1`, wheel + sdist |
| 7 | instalación limpia de wheel | `site-packages`, `pip check` correcto, flujo completo |
| 8 | instalación limpia de sdist | ídem, resultado funcional equivalente |
| 9 | independencia, inventario de API, matriz de integración, parche, informe | entregado |

## B. Línea base verificada antes de tocar nada

| comprobación | valor observado |
|---|---|
| ruta del workspace | `/private/tmp/kuyen_hardening_01/kuyen` (`/tmp` → `/private/tmp`) |
| HEAD | `5fd8777a8305097792380fceb9ff861de208147a`, HEAD *detached*, sin rama |
| `VERSION` inicial | `0.2.0` |
| `git status --porcelain` | **17 ` M` + 19 `??`**, exactamente el estado del informe 04 |
| parches 01–04 | `6ce8914…d33`, `67bc04b…ade`, `7d6ea6d…273`, `6ca0724b…f1a` — los cuatro intactos |
| informes 01–04 | presentes en `docs/reports/` (21 507 / 21 805 / 21 509 / 34 099 B) |
| correcciones A1–A3, M1–M2, M3–M5, B3, exp. 03 | todas presentes (comprobadas por símbolo, no por informe) |
| `sys.executable` | `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3` (3.13.1) |
| `kuyen.__file__` | `/private/tmp/kuyen_hardening_01/kuyen/src/kuyen/__init__.py` |
| suite de línea base | **311 tests · 309 passed · 0 failed · 2 skipped · 7,3 s** |
| cobertura de línea base | **78 %** (8 029 sentencias, 1 787 sin cubrir) |

No había modificaciones nuevas sin explicar; no se ejecutó `git reset`, `clean`, `checkout`,
`rebase` ni `cherry-pick` en ningún momento, y no se limpió ningún archivo no rastreado.
La evidencia de identidad está en `release_candidate_05/evidence/00_baseline_identity.txt` y
`01_suite_baseline.xml`.

---

## C. M6 — escalabilidad del commit y del ledger

### C.1 Qué hace el flujo, reconstruido

Un commit recorre: validación de esquema + referencias → sidecar y registro de proyección →
hashes → objetos en staging → blobs content-addressed (con verificación) → **manifiesto
(commit point)** → índice → ledger (3 eventos) → outbox → `CURRENT` (CAS) → limpieza de
staging. La lectura del ledger entraba por dos sitios:

| punto | lecturas completas del ledger por commit |
|---|---|
| `ledger.append_event` → `repair_ledger` + `events` | **2 por evento × 3 eventos** |
| `registry.index_version` → escaneo completo del índice | 1 por commit |
| total medido con instrumentación | **9 por commit** |

### C.2 Banco de pruebas (sin LLM, sin OpenViking, sin red)

`release_candidate_05/benchmarks/m6_bench.py` y `m6_history_bench.py` generan stores
temporales y documentos deterministas de tamaño parametrizable (100 / 500 / 1 000 / 5 000
nodos; ledger con 10 / 100 / 500 / 1 000 eventos) y cuentan lo que el código **realmente
hace** envolviendo 6 funciones en los espacios de nombres del paquete (46 enlaces), sin
tocar `src/kuyen`. La mediana se calcula sobre 3 repeticiones sin instrumentar; los
contadores se toman en una repetición aparte para no contaminar el tiempo. Un perfil
`cProfile` de un commit de 1 000 nodos atribuye el costo dominante: validación de esquema
(0,35 s de 0,93 s), objetos y re-verificación de blobs (0,31 s), serialización (0,12 s).

### C.3 El defecto, medido

**Costo por evento al añadir historia** (lote real de 50 eventos sobre un ledger existente):

| eventos ya en el ledger | antes: ms/evento | antes: lecturas completas/evento | antes: bytes leídos/evento |
|---|---:|---:|---:|
| 102 | 1,06 | 2,0 | 103 617 |
| 502 | 3,55 | 2,0 | 437 217 |
| 1 002 | 4,88 | 2,0 | 854 268 |
| 2 002 | 9,82 | 2,0 | 1 690 268 |

**Costo total de construir un ledger** (N eventos, medido de cero):

| eventos | antes: total | antes: ms/evento |
|---|---:|---:|
| 201 | 0,135 s | 0,676 |
| 401 | 0,428 s | 1,070 |
| 801 | 1,608 s | 2,010 |
| 1 601 | 6,033 s | 3,771 |

Cuadrático: 4× eventos → ~4× por evento → ~16× el total (medido 11,9× eventos → 44,7×
tiempo). El motivo es exacto y no una intuición: `append_event` llamaba a `repair_ledger()`
(incluye `read_classified`, que parsea el fichero completo) y después a `events()` (otra
lectura completa y otro parseo) para obtener `seq` y `prev_event_hash`, que sólo están en el
último registro.

### C.4 Corrección

| cambio | archivo |
|---|---|
| `read_last_line()`: inspecciona el final de un JSONL abriendo una ventana desde el final que crece hasta contener dos saltos de línea | `canonical.py` (nuevo) |
| `iter_lines_reverse()`: recorre las líneas del final hacia el principio, perezosamente | `canonical.py` (nuevo) |
| `read_tail()`: `seq` y `prev_event_hash` desde el último registro, con estado `usable` | `lifecycle/ledger.py` (nuevo) |
| `append_event()`: enlaza con la cola en O(1); si la cola no es un registro usable cae al camino completo (repara cola truncada, rechaza corrupción) | `lifecycle/ledger.py` |
| `index_version()`: busca la versión recorriendo el índice desde el final | `storage/registry.py` |

Nada de esto cambia el formato persistido, ni la secuencia, ni el enlace de hashes, ni la
protección concurrente de M1 (todo sigue dentro de `writer_lock`).

### C.5 El mismo banco, después

**Costo por evento:**

| eventos ya en el ledger | después: ms/evento | lecturas completas/evento | bytes leídos/evento |
|---|---:|---:|---:|
| 102 | 0,315 | 0,0 | 0 |
| 502 | 0,206 | 0,0 | 0 |
| 1 002 | 0,195 | 0,0 | 0 |
| 2 002 | 0,191 | 0,0 | 0 |

**Costo total de construir un ledger:**

| eventos | antes | después | factor | ms/evento después |
|---|---:|---:|---:|---:|
| 201 | 0,135 s | 0,037 s | 3,6× | 0,183 |
| 401 | 0,428 s | 0,070 s | 6,1× | 0,176 |
| 801 | 1,608 s | 0,138 s | 11,7× | 0,172 |
| 1 601 | 6,033 s | 0,292 s | **20,7×** | 0,183 |

Lineal: el costo por evento es constante (0,17–0,18 ms) sea cual sea la historia.

**Commit completo (grafo × ledger):**

| nodos | eventos sembrados | commit antes (ms) | commit después (ms) | lecturas completas del ledger antes → después |
|---|---:|---:|---:|---:|
| 100 | 0 | 56,7 | 59,4 | 9 → **0** |
| 100 | 10 | 61,5 | 55,1 | 9 → **0** |
| 100 | 100 | 60,5 | 54,7 | 9 → **0** |
| 100 | 500 | 66,9 | 56,6 | 9 → **0** |
| 100 | 1 000 | 74,3 | 53,6 | 9 → **0** |
| 500 | 0 | 231,8 | 224,9 | 9 → **0** |
| 1 000 | 0 | 446,5 | 443,0 | 9 → **0** |
| 5 000 | 0 | 2 129,4 | 2 185,2 | 9 → **0** |

Las lecturas «0» se midieron con un espía sobre `read_classified` **durante** el commit
(`evidence/60_commit_ledger_reads.txt`: 0 lecturas con 0, 200 y 1 000 eventos en el ledger).
La cifra «1» que aparece en los JSON del banco es la lectura que el propio arnés hace
después, al contar eventos para el informe.

A 1 000 eventos el commit baja de 74,3 a 53,6 ms (−28 %) y **el coste deja de depender de la
historia**: con 1 000 eventos el commit cuesta lo mismo que con 10 (53,6 vs 55,1 ms, ruido).
En el eje del grafo el tiempo no cambia porque el trabajo dominante es otro (validación de
esquema, hasheo de objetos y re-verificación de blobs), y ese trabajo es **lineal en el
tamaño del grafo**: 50× nodos → 37× tiempo (100 → 5 000 nodos).

### C.6 Por qué NO se tocó el resto

El perfil muestra que el commit escala linealmente con el grafo por tres razones inherentes
al modelo: cada versión es una foto completa, cada objeto se valida contra el esquema
productivo y `put_blob` **re-verifica el contenido de todo blob existente** antes de
reutilizarlo (20 004 lecturas, 11,3 MB a 5 000 nodos). Quitar cualquiera de las tres
cambiaría garantías, no algoritmos, y el encargo prohíbe sacrificar integridad por tiempo.
Queda medido y documentado en `CHANGELOG.md`, no escondido.

### C.7 Límite residual declarado del índice

`index_version` recorre el índice desde el final, así que **re-indexar** una versión (el
camino idempotente que usa `recover_pending`) cuesta una lectura de un bloque: 0,04–0,14 ms.
Pero indexar una versión **nueva** debe probar su ausencia y eso sigue siendo lineal en el
número de versiones (`evidence/61_index_residual.txt`):

| versiones en el índice | versión ausente | versión presente |
|---|---:|---:|
| 100 | 0,31 ms | 0,04 ms |
| 500 | 0,88 ms | 0,04 ms |
| 2 000 | 3,19 ms | 0,07 ms |
| 5 000 | 8,21 ms | 0,14 ms |

Es un término **bounded** (~1,6 ms por 1 000 versiones) y muy por debajo del trabajo del
commit; eliminarlo exigiría un formato nuevo (marcador por versión o un flag de «entrada
nueva» en el escritor), y esta pasada no está autorizada a cambiar el formato persistido.
Se declara en lugar de silenciarse.

### C.8 Pruebas de regresión (M6)

`tests/lifecycle/test_m6_append_scaling.py` — 8 pruebas, cuatro de ellas fallan en el árbol
previo (ver §N.2): append no parsea el ledger completo (un `read_classified` que lanza
demuestra que no se llama), bytes leídos acotados (< 64 KiB con un ledger de 400+ KB),
cola truncada todavía reparada con registro en `ledger/recovery/`, corrupción en el medio
sigue fallando cerrado para los lectores, índice: 1 línea leída para re-indexar entre 600, y
append exactamente una vez para una versión ausente. **La suite completa (M1 hilos +
multiproceso) sigue verde después del cambio.**

---

## D. B1 — `recover_pending` clasificaba mal el staging publicado

### D.1 Reconstrucción y causa

Un commit crea `staging/<commit_id>/INTENT.json` antes de escribir nada y borra el directorio
sólo al final, después del CAS de `CURRENT`. `recover_pending` recorría los stagings y
preguntaba:

```python
version_id = version_id_for(read_json(intent)["identity_core"]) if "identity_core" in read_json(intent) else None
```

`INTENT.json` **nunca** contiene `identity_core`: contiene `commit_id`, `kuyen_id`,
`kuyen_version`, `canonical_graph_hash`, `parent_version_id`, `antu_id`, `unit_revision`,
`created_at` y `stages_completed`. Por tanto `version_id` era siempre `None`, el motivo era
siempre `STAGING_WITHOUT_PUBLISHED_MANIFEST`, **incluido el staging de un commit ya
publicado**, y el directorio se borraba antes de que nadie pudiera distinguir los dos casos.
Además, con un único manifiesto publicado y sin `CURRENT`, la recuperación dejaba el store
en un estado que `verify()` rechazaba (`CURRENT pointer is missing`).

Reproducción (`/tmp/kuy05/reproduce_b1_b2.py`, árbol base + 4 parches):

```
crash at before_manifest  manifest_published=False reported=STAGING_WITHOUT_PUBLISHED_MANIFEST verify_ok=True
crash at after_manifest   manifest_published=True  reported=STAGING_WITHOUT_PUBLISHED_MANIFEST verify_ok=False
```

### D.2 Corrección

| pieza | comportamiento |
|---|---|
| `classify_staging(store, path)` (nuevo) | deriva la identidad **como la deriva el commit** (los seis campos de `identity_core`, todos escritos en `INTENT.json`) y usa el **manifiesto** como evidencia de publicación |
| `NOT_PUBLISHED` | no hay manifiesto: el commit murió antes del commit point; el staging se elimina |
| `PUBLISHED_COMPLETE` / `PUBLISHED_PARTIAL` | el manifiesto existe; se completan índice, ledger y outbox, y sólo entonces se elimina el staging; `actions_completed` dice qué faltaba |
| `UNCLASSIFIED` | sin `INTENT.json` legible, identidad incompleta o manifiesto que no concuerda: **se conserva** y se informa en `staging_kept` |
| `current_adopted` | si hay un único manifiesto y ningún `CURRENT`, se adopta con un evento `RECONCILIATION` (`CURRENT_CREATED_FOR_ACCEPTED_VERSION`) |
| `current_ambiguous` | con más de un candidato no se adivina: se informa el fork |

La clasificación ocurre **antes** de completar, y la limpieza **después**: el orden es parte
del arreglo. Todo es condicional a la ausencia de su propia evidencia, así que sigue siendo
idempotente.

Salida del mismo guion sobre el árbol corregido:

```
crash at before_manifest  manifest_published=False reported=...interrupted before the commit point state=NOT_PUBLISHED verify_ok=True
crash at after_manifest   manifest_published=True  reported=the manifest is published; the staging is only pending cleanup state=PUBLISHED_PARTIAL verify_ok=True
```

### D.3 Pruebas (8)

`tests/lifecycle/test_b1_staging_classification.py`: las tres clasificaciones (sin
manifiesto, con manifiesto tras el commit point, sin `INTENT.json` legible), la recuperación
de cada estado, `PUBLISHED_COMPLETE` sin acciones, staging no atribuible **conservado** con
su contenido intacto, no duplicación de versiones/eventos/índice/outbox en dos
recuperaciones consecutivas, y `verify()` correcto después de recuperar. Una de ellas usa
los `Failpoint` reales del escritor (`before_manifest`, `after_manifest`), no una simulación.

---

## E. B2 — restauración sobre un directorio existente

### E.1 Contrato previo, reconstruido

`restore_backup` verificaba el backup, comprobaba `target.exists() and any(target.iterdir())`
—es decir, **aceptaba explícitamente** un directorio existente y vacío— y a continuación
llamaba a `shutil.copytree(backup_path, target)`, que con el destino existente lanza
`FileExistsError`. La validación y la operación decían cosas distintas. El destino no se
validaba como ruta: un symlink, un archivo, el propio backup o un directorio que lo
contuviera llegaban hasta la copia.

Reproducción (mismo guion, árbol previo):

```
restore failed: FileExistsError: [Errno 17] File exists: '.../target'
```

### E.2 Corrección

| situación del destino | antes | ahora |
|---|---|---|
| no existe | se creaba | se crea (con padres) |
| existe y vacío | `FileExistsError` | **se usa** |
| existe y no vacío | `BackupError` | `BackupError`, contenido **byte a byte intacto** |
| es un archivo | llegaba a `copytree` | `BackupError` antes de tocar nada |
| es un symlink | se escribía a través | `BackupError` |
| es el backup / está dentro / lo contiene | no se comprobaba | `BackupError` (rutas resueltas) |
| ya contiene una restauración | `BackupError` | `BackupError` |

Se conserva la disciplina de A3 (comparación de rutas **resueltas**, nada se toca antes de
validar) y se añade limpieza acotada: si la copia falla, se elimina **sólo** lo que esta
operación creó (el destino nuevo completo, o el contenido de un destino que estaba vacío).
El backup no se modifica nunca.

### E.3 Pruebas (12)

`tests/storage/test_b2_restore_target.py`: destino inexistente, destino existente vacío,
restauración + `verify()` + **nueva escritura** sobre el store restaurado, destino no vacío
rechazado con instantánea de hashes antes/después idéntica, archivo, symlink, el propio
backup, destino dentro del backup, destino que contiene el backup, restauración repetida
rechazada conservando la primera, backup byte a byte idéntico después de restaurar, y
`KuyenMemory.restore` devolviendo una memoria usable. **10 de las 12 fallan en el árbol
previo.**

---

## F. M7 — el extra `[dev]` no podía ejecutar la suite

`tests/unit/test_adapter.py` y `tests/unit/test_013_ingestion.py` importan
`kuyen.adapters.openviking` en la cabecera del módulo; ese módulo hace `import httpx`, que
estaba sólo en el extra `openviking`. Con `pip install -e ".[dev]"` el entorno no podía
siquiera **recolectar**:

```
$ python -m pytest --collect-only -q        # entorno limpio con el [dev] anterior
E   ModuleNotFoundError: No module named 'httpx'
ERROR tests/integration/test_openviking_real.py
ERROR tests/unit/test_013_ingestion.py
ERROR tests/unit/test_adapter.py
!!!!!!!! Interrupted: 3 errors during collection !!!!!!!!
```

Corrección, separando responsabilidades:

```toml
openviking = ["httpx>=0.25"]
dev = ["pytest>=7.0", "pytest-cov>=4.0", "build>=1.0", "twine>=5.0", "httpx>=0.25"]
```

`httpx` **no** entra en la instalación base (sigue siendo dependencia opcional del adaptador
y de las pruebas que lo ejercitan) y `pytest-cov` cubre el comando de cobertura documentado.
Verificación en un `venv` nuevo (`release_candidate_05/install_tests/venv-dev`):

```
$ pip install -e ".[dev]"
$ python -m pytest --collect-only -q     → 339 tests recolectados
$ python -m pytest -q -p no:cacheprovider → 337 passed, 2 skipped
$ python -m pytest -q --cov=kuyen          → 78 % (8 180 sentencias)
```
Sin `PYTHONPATH`, sin instalación global, sin `conftest` que oculte imports.

---

## G. B5 — el mínimo de `setuptools` declarado no era real

El `pyproject.toml` declaraba `setuptools>=68` y usaba metadatos PEP 639: `license =
"Apache-2.0"` (expresión SPDX como cadena) y `license-files = ["LICENSE"]` en `[project]`.
Construir **exactamente** con el mínimo declarado falla:

```
$ python -m build --no-isolation          # setuptools 68.0.0, wheel 0.48.0
ValueError: invalid pyproject.toml config: `project.license`.
  configuration error: `project.license` must be valid exactly by one definition (2 matches found):
      - keys: 'file': {type: string}  required: ['file']
      - keys: 'text': {type: string}  required: ['text']
```

Barrido empírico (mismo árbol, `--no-isolation`, comprobando la versión instalada en cada
paso porque una instalación fallida deja la anterior):

| setuptools | resultado |
|---|---|
| 68.0.0 (mínimo declarado) | falla: `project.license` |
| 75.3.2 | falla: `project.license` |
| 76.0.0 | falla: `project.license` |
| 76.1.0 | falla: `project.license` |
| 77.0.1 | **sdist + wheel correctos** |
| 77.0.3 | sdist + wheel correctos |

`77.0.0` no está publicado en PyPI (la serie salta de 76.1.0 a 77.0.1), así que el mínimo
honesto y comprobado es **77.0.1**:

```toml
[build-system]
requires = ["setuptools>=77.0.1", "wheel"]
build-backend = "setuptools.build_meta"
```

La alternativa —degradar los metadatos a `license = {text = "Apache-2.0"}` para conservar
68— habría sustituido un metadato estándar y legible por máquina (`License-Expression`,
Metadata-Version 2.4) por una forma obsoleta, además de dejar la comprobación de licencia del
CI dependiendo de un campo heredado. No se declara compatibilidad con ninguna versión que no
se haya construido.

---

## H. Identidad de versión y construcción del candidato

### H.1 Por qué `0.2.1rc1`

* La versión pública de referencia es `0.2.0`; el artefacto **no** puede llamarse igual.
* Los cambios son aditivos y compatibles con el formato persistido (store 1.0.0, sidecar
  1.0.0, outbox 1.0.0, backup 1.0.0) y no retiran ningún nombre público, así que no procede
  un salto de minor ni de major.
* Hay dos cambios de contrato documentados (el append del ledger ya no revalida toda la
  cadena; `verify()`/`recover()` devuelven bloques adicionales), lo que excluye presentarlo
  como un simple `0.2.0` recompilado.
* Es una preliminar PEP 440 (`rc1`) porque nada se publica en esta etapa: `pip` no la
  instalará por defecto y no puede confundirse con la línea publicada.

`VERSION`, `README.md` (línea de estado) y `CHANGELOG.md` se actualizaron en el workspace
controlado; no se creó ningún tag, commit ni publicación.

### H.2 Artefactos

| artefacto | bytes | SHA-256 |
|---|---:|---|
| `kuyen-0.2.1rc1-py3-none-any.whl` | 219 027 | `0636583c9fe7e153ca496642d5204ce4cd1ed46b5b6f979c125740f2da6afcc9` |
| `kuyen-0.2.1rc1.tar.gz` | 201 813 | `e8064d4594b049d3da7cfc59c7bfc7f2b4ab114b8699fef0fca69bbf52d7663d` |

| dato de construcción | valor |
|---|---|
| backend | `setuptools.build_meta` |
| `requires` | `setuptools>=77.0.1`, `wheel` |
| herramienta | `build 1.6.1`, entorno de aislamiento por defecto |
| setuptools del artefacto entregado | 84.2.1 (el que resuelve el aislamiento) |
| mínimo comprobado aparte | **77.0.1** con `--no-isolation` |
| Python de construcción | 3.13.1 (arm64, macOS) |
| commit de referencia | `5fd8777a…` + parches 01–04 (intactos) |

`build_info.json` recoge todo esto, incluidos los hashes de los cuatro parches anteriores y
el del parche de esta pasada.

### H.3 Auditoría del contenido

| comprobación | wheel | sdist |
|---|---|---|
| número de entradas | 101 | 137 |
| `validation/canonical.py` (A1) | sí | sí |
| `provenance.py` (M4) | sí | sí |
| persistencia completa (`storage/`, `lifecycle/`, `backup/`, `projection/`, `recovery/`) | sí | sí |
| esquemas (10), ontologías (5), skills (4), `py.typed` | sí | sí |
| `LICENSE` | `dist-info/licenses/LICENSE` | raíz |
| los 12 documentos de la raíz que el `README` enlaza + `VERSION` + `pyproject.toml` + `MANIFEST.in` | — | sí |
| `.env`, tokens, credenciales, claves | no | no |
| stores reales, backups de desarrollo, logs | no | no |
| `tests/`, `experiments/`, `docs/` | no | no (podado en `MANIFEST.in`) |
| `__pycache__`, `.pytest_cache`, `.coverage`, `*.pyc` | no | no |

`MANIFEST.in` se añadió porque el sdist no incluía `CHANGELOG.md` ni el resto de documentos
que el `README` enlaza (12 ficheros): quien reciba sólo el sdist tendría enlaces rotos. La
regla es `include *.md` en la raíz, con `prune docs` y `prune tests`, y no se añadió nada al
wheel, que no lleva documentación. El sdist contiene todo lo necesario para reconstruir el
wheel (se comprobó instalándolo, §I.2).

---

## I. Instalación limpia y flujo funcional

### I.1 Wheel en un entorno limpio

```
$ python -m venv venv-wheel && pip install dist/kuyen-0.2.1rc1-py3-none-any.whl
sys.executable : .../install_tests/venv-wheel/bin/python
kuyen.__file__ : .../venv-wheel/lib/python3.13/site-packages/kuyen/__init__.py
kuyen.__version__ : 0.2.1rc1     (metadatos instalados)
pip check      : No broken requirements found.
dependencias   : jsonschema 4.26.0, PyYAML 6.0.3, attrs, referencing, rpds-py
                 (ningún SDK LLM, ningún OpenViking, ningún httpx)
```

Sin `PYTHONPATH`, sin instalación editable, ejecutado desde `/tmp` (fuera del repositorio).

### I.2 Sdist en otro entorno limpio

```
$ python -m venv venv-sdist && pip install --no-cache-dir dist/kuyen-0.2.1rc1.tar.gz
kuyen.__file__ : .../venv-sdist/lib/python3.13/site-packages/kuyen/__init__.py
kuyen.__version__ : 0.2.1rc1
pip check      : No broken requirements found.
```

`--no-cache-dir` fuerza a construir desde el sdist (no reutiliza el wheel ya construido).

### I.3 Flujo funcional (mismo guion, ambos artefactos)

`install_tests/flow_check.py` usa **sólo** la API pública del paquete instalado. Documento
determinista: 4 líneas con **CRLF**, Unicode (`Ñuble`, `ó`, `récord`), 2 entidades, 1
relación, 1 afirmación, 2 evidencias con offsets, ids en el formato que exige el esquema.

| paso | comprobación | resultado |
|---|---|---|
| 1 | `create` deja la memoria vacía | `current() is None` |
| 2-7 | MAPU + documento + afirmaciones + evidencias + validación canónica + commit | `VER-08c272a8cd34`, counts `{assertions:1, coverage:1, entities:2, evidence:2, mapus:1, relations:1, source_units:1}` |
| — | `source_bytes_sha256` es el hash de los bytes originales | `033c1074…630b` ✓ |
| — | `newline_policy`, `offset_unit`, `encoding`, `source_hash_scope` persistidos | `PRESERVED`, `unicode_codepoint`, `utf-8`, `SOURCE_BYTES` |
| 8 | `verify()` | `ok`, sin problemas |
| 9 | `history()`, `lineage()` | 1 revisión, 1 versión en la cadena |
| — | `evidence_of` + offsets | la cita es exactamente `content[char_start:char_end]` |
| — | `trace` | afirmación → evidencia → `SOURCE_UNIT` `u00` → MAPU, con el hash de contenido del MAPU |
| 10-11 | `backup` + `verify_backup` | `SEALED`, 24 archivos, `ok` |
| 11-12 | `restore` a un directorio existente y vacío + `verify()` | `ok`, misma versión `VER-08c272a8cd34` |
| 13 | `recover_from_store` | reconstruye la versión, `hashes_match`, `VALID_WITH_LOSSY_PROJECTION` |
| 14 | `execute_antu` + `commit` (segunda escritura) | `VALIDATED` → `VER-104f4c58799f`, 2 versiones |
| — | ledger tras la segunda escritura | 9 eventos, estado `INTACT` |
| — | `pending()`, `recover()` repetido, `verify()` | staging `[]`, `staging_discarded == []`, `ok` |

**Comparación wheel vs sdist:** 38 claves comparadas, **0 diferencias**, todos los booleanos
`true`, mismos identificadores de versión y mismo número de archivos de backup. El
`backup_id` difiere (incluye `created_at`) y la ruta del venv difiere, como es esperable; no
se comparan. Resultados en `install_tests/flow_wheel.json` y `flow_sdist.json`.

---

## J. Independencia de proveedores y del runtime

No se comprobó mirando `pyproject.toml`, sino en los entornos instalados:

| comprobación | wheel | sdist |
|---|---|---|
| `httpx`, `ollama`, `openai`, `anthropic`, SDK de proveedor | **no instalados** | **no instalados** |
| `openviking` | **no instalado** | **no instalado** |
| módulos `kuyen.*` que importan el adaptador OpenViking al importar el paquete | ninguno (`adapters/__init__.py` documenta que no se importa nada del núcleo) | ídem |
| módulos de LeftraruOS | no existen en el entorno (`import leftraru` falla) | ídem |
| rutas relativas al repositorio | ninguna: el flujo se ejecutó desde `/tmp` y el store creado está en `/tmp` | ídem |
| credenciales o red | ninguna: `create`, `import_canonical`, `verify`, `history`, `backup`, `restore`, `recover`, `recover_from_store`, `execute_antu`, `commit` funcionaron sin red | ídem |

El adaptador OpenViking sigue existiendo como extra opcional (`.[openviking]`) y la suite lo
ejercita en el entorno de desarrollo, pero **no** es necesario para ninguna garantía canónica.

---

## K. Inventario de la API pública para un consumidor externo

Superficie real: `kuyen` (raíz) y `kuyen.errors`. Todo lo demás es interno.

```python
from kuyen import KuyenMemory, build_document, __version__
from kuyen.errors import (KuyenError, StoreError, CommitError, ConflictError, ValidationRejected,
                          BackupError, ProjectionError, ImmutableViolation, ExportError,
                          AntuConflictError, InjectedFailure)
```

### K.1 Construcción y lectura

| operación | parámetros | resultado | excepciones | efecto persistente |
|---|---|---|---|---|
| `KuyenMemory.create(path, *, leftraru_id, purpose="canonical memory")` | ruta, unidad | `KuyenMemory` | `StoreError` si ya hay store | crea `FORMAT.json`, directorios y el lock |
| `KuyenMemory.open(path)` | ruta | `KuyenMemory` | `StoreError` (no es store / formato no soportado) | ninguno (no repara) |
| `memory.status()` | — | formato, unidad, puntero, counts, integridad | — | ninguno |
| `memory.current()` / `versions()` / `lineage(id)` | — | `MemoryVersion` / lista | — | ninguno |
| `memory.graph(id=None)` | — | grafo canónico verificado | `StoreError` | ninguno |
| `memory.sidecar(id=None)` | — | sidecar del MAPU (incluye `source_bytes_sha256`, `newline_policy`, `offset_unit`) | `StoreError` | ninguno |
| `memory.history()` / `ledger()` / `ledger_state()` | — | revisiones de unidad / eventos / clasificación del ledger | `StoreError` si el ledger está corrupto | ninguno |
| `memory.source_unit(unit_id, version_id=None)` | — | `SOURCE_UNIT` con su texto verificado | `StoreError` | ninguno |
| `memory.evidence_of(claim_id, version_id=None)` | — | evidencias que sostienen la afirmación | `StoreError` | ninguno |
| `memory.trace(claim_id, version_id=None)` | — | afirmación → evidencia → `SOURCE_UNIT` → MAPU | `StoreError` | ninguno |

### K.2 Escritura gobernada

| operación | parámetros | resultado | excepciones | efecto persistente |
|---|---|---|---|---|
| `memory.execute_antu(antu, *, mapu_source=None)` | dict ANTÜ + fuente | `AntuExecution` (`status`: `VALIDATED`, `REJECTED`, `NO_SEMANTIC_CHANGE`, `CONFLICT`, `REPLAYED`) | `ValidationRejected` (con `report["problems"]`), `AntuConflictError` | eventos `ANTU_*` y revisión de unidad; **ninguna versión** |
| `memory.commit(execution)` | ejecución `VALIDATED`/`REPLAYED` | `CommitResult` (`.version`, `.operation_key`, `.antu_id`) | `CommitError`, `ConflictError` (base obsoleta) | blobs, manifiesto, índice, ledger, outbox, `CURRENT` |
| `memory.import_canonical(document, *, antu_id="ANTU-IMPORT")` | documento canónico | `CommitResult` | `CommitError` (esquema/validación), `ConflictError` | ídem |
| `memory.record_failed_antu(antu, *, reason)` | dict + motivo | recibo del evento | `StoreError` | evento `ANTU_REJECTED` + revisión |
| `build_document(graph, mapu_texts, *, mapu_versions=None, source_uris=None, source_bytes=None, encodings=None)` | grafo aceptado + fuentes | documento canónico | `ExportError` | ninguno (es una función pura) |

### K.3 Integridad, backup y recuperación

| operación | resultado | excepciones |
|---|---|---|
| `memory.verify()` | `{ok, problems, versions[], current, registry, objects, ledger, unit_history}` | nunca lanza |
| `memory.pending()` | staging, versiones sin confirmar, versiones sin revisión | `StoreError` |
| `memory.recover()` | `{completed, staging_discarded, staging_kept, current_advanced, current_adopted, current_ambiguous, ledger, projections, unit_history}` | `StoreError` si el ledger está corrupto en el medio |
| `memory.backup(target)` | `backup_id`, versiones, `root_hash`, `files`, `integrity_status` | `BackupError` (destino inseguro) |
| `KuyenMemory.verify_backup(path)` | informe verificado | `BackupError` |
| `KuyenMemory.restore(backup, target)` | `KuyenMemory` restaurada | `BackupError` (backup corrupto, destino no vacío/archivo/symlink/relacionado con el backup) |
| `KuyenMemory.recover_from_store(path, *, workdir, contract_snapshot=None)` | reconstrucción versión a versión con `hashes_match` | `StoreError` |

### K.4 Interfaces que deberían consumir los agentes del runtime

1. `KuyenMemory.open(path)` — una memoria por unidad, abierta una vez.
2. `execute_antu(...)` → `commit(...)` — **el** camino de escritura de un agente; `VALIDATED`
   no es una promesa de commit (el CAS o el I/O pueden fallar después) y ese estado se
   representa, no se oculta.
3. `import_canonical(document)` — para un productor que ya entrega un documento canónico.
4. `verify()`, `pending()`, `recover()` — salud y recuperación tras un corte.
5. `trace(claim_id)` / `evidence_of(claim_id)` / `source_unit(unit_id)` — para citar.
6. `backup()` / `verify_backup()` / `restore()` — ciclo de vida operativo.
7. `status()`, `current()`, `versions()`, `history()` — para paneles y auditoría.

Nada de esta lista exige importar módulos internos. `memory.store` existe para adaptadores
de bajo nivel y **no** debería ser el mecanismo normal de operación.

---

## L. Matriz de preparación para la integración con LeftraruOS

No se clonó ni se modificó LeftraruOS. Lo que sigue es el mapa de preguntas que la etapa
`LEFTRARU_KUYEN_RUNTIME_INTEGRATION_01` tendrá que responder **contra el esquema y el
adaptador reales**, no una solución inventada.

| área | pregunta de integración | lo que KÜYEN ya ofrece hoy | lo que falta decidir |
|---|---|---|---|
| MAPU | ¿cómo se registra cada entrada? | `build_document(..., source_bytes=...)` + `import_canonical`; procedencia de bytes, `newline_policy`, `offset_unit`, unidades de fuente verificadas | quién produce el MAPU (lector de fuentes del runtime) y con qué codificación declarada |
| Afirmaciones | ¿cómo se representan entidades y relaciones? | grafo canónico con `entities/relations/assertions/evidence` validado por esquema productivo (A1) | mapeo de los tipos del runtime al perfil de ontología |
| Evidencia | ¿cómo se conserva fuente, hash y offsets? | `evidence` con `char_start/char_end`, `offset_unit`, `source_sha256` verificado contra el texto (M4) | política de citas del runtime (¿offsets de código de punto Unicode?) |
| ANTÜ | ¿cómo se relaciona con operaciones y decisiones? | ciclo `execute_antu` → `commit`, estados explícitos, `ValidationRejected` con problemas, replay por `antu_id` | quién firma la decisión humana y cómo se registra |
| Versiones | ¿cómo se registra la evolución? | una versión inmutable por commit, `parent_version_id`, `CURRENT` con CAS, linaje | política de ramas/fork (hoy: se informa `current_ambiguous`, no se adivina) |
| Eventos | ¿cómo se preserva el linaje de ejecución? | ledger encadenado por hash, 11 tipos de evento, reparación sólo de cola truncada, append O(1) (M6) | anclaje externo del head (no implementado; ver §M) |
| Proyecciones | ¿cómo se evitan pérdidas de campos? | outbox con reclamo atómico, registro de proyección, `unrepresented_fields` en el sidecar, reconciliación | decisión sobre los **18 campos** que hoy pierde `runtime/memory_canonical`: hay que enumerarlos contra el esquema canónico |
| Recuperación | ¿cómo se reconstruye una operación interrumpida? | `recover()` clasifica staging (B1), adopta `CURRENT` si es inequívoco, es idempotente; `recover_from_store` reconstruye desde el store solo | quién ejecuta la recuperación (operador o runtime) y con qué frecuencia |
| API | ¿qué interfaz usará el runtime? | `KuyenMemory` (§K) sin imports internos | envoltorio delgado en el runtime para inyectar la ruta del store |

**Recomendación arquitectónica (sin cambios en esta etapa):** KÜYEN debe ser la única
autoridad de memoria. `runtime/memory_canonical` puede sobrevivir como fachada de
compatibilidad, pero sus lecturas y escrituras deben delegar en KÜYEN; dos stores
autoritativos y dos historiales independientes son el escenario que hay que evitar. La
pérdida reportada de 18 campos **no** se resuelve aquí: requiere leer el esquema y el
adaptador reales y decidir, campo por campo, si se migran, se preservan o se transforman con
procedencia.

---

## M. Seguridad y distribución

| comprobación | resultado |
|---|---|
| secretos en el árbol y en los artefactos | ninguno (`.env`, `*.pem`, `*.key` ausentes; auditoría de contenido del wheel y del sdist) |
| licencia | `Apache-2.0`, `LICENSE` en la raíz del sdist y en `dist-info/licenses/` del wheel, `License-Expression` en los metadatos |
| metadatos | `Metadata-Version: 2.4`, `Requires-Python: >=3.10`, `Requires-Dist` sólo `jsonschema`, `PyYAML`; extras separados |
| dependencias | `pip check` correcto en los tres entornos (dev, wheel, sdist) |
| hashes | SHA-256 de ambos artefactos en `build_info.json`, `SHA256SUMS.txt` y este informe |
| integridad de los artefactos | contenido auditado archivo por archivo (§H.3) |
| stores de prueba | todos bajo `tmp`/`/tmp`; ningún store real leído ni escrito |
| informes y parches anteriores | intactos (mismos SHA-256 al inicio y al final) |
| firma criptográfica / autenticidad externa | **no existe y no se declara** (ver `SECURITY.md`: no hay raíz de confianza) |
| publicación | **ninguna**: sin PyPI, sin GitHub Release, sin tag, sin commit |

---

## N. Reproducibilidad

### N.1 El parche

`/tmp/kuyen_hardening_01/release_candidate_05.patch` contiene **todos** los cambios de código,
pruebas, configuración, versión y documentación de esta pasada (ningún binario de wheel ni de
sdist). No se alteró el índice Git para generarlo: se construyó en un repositorio temporal a
partir del árbol `base + 4 parches` y del workspace.

| comprobación | resultado |
|---|---|
| aplica sobre `5fd8777a…` + parches 01–04 | sí, sin conflictos ni avisos |
| árbol reconstruido vs workspace | `diff -ruN` **vacío** |
| suite sobre el árbol reconstruido | verde (§N.3) |
| parches 01–04 | no modificados (mismos SHA-256) |
| archivos | **17 sin contar este informe** (+1 016 / −48); el parche completo son 18 archivos, +1 746 / −48 |

### N.2 Reproducción de los defectos antes de corregir

En un worktree limpio con `base + 4 parches` (estado previo a esta pasada):

| frente | evidencia |
|---|---|
| M6 | 4 de las 8 pruebas nuevas fallan: append parsea el ledger completo, bytes leídos crecen con el ledger, la corrupción en el medio ya no bloquea el append (contrato nuevo), el índice escanea 600 líneas en lugar de 1 |
| B1 | guion de reproducción: un staging con manifiesto publicado se informa como `STAGING_WITHOUT_PUBLISHED_MANIFEST` y `verify()` queda en `False` |
| B2 | guion de reproducción: `FileExistsError` en destino existente y vacío; 10 de 12 pruebas nuevas fallan |
| M7 | `pip install -e ".[dev]"` + `pytest --collect-only` → `ModuleNotFoundError: No module named 'httpx'` en 3 módulos |
| B5 | `python -m build --no-isolation` con `setuptools==68.0.0` → `invalid pyproject.toml config: project.license` |

Ninguno de los cinco hallazgos se dio por supuesto: los cinco se ejecutaron primero.

### N.3 Suite final

```
antes : 311 tests · 309 passed · 0 failed · 2 skipped · 78 % (8 029 sentencias)
después: 339 tests · 337 passed · 0 failed · 2 skipped · 78 % (8 180 sentencias)
        +28 pruebas (M6 8, B1 8, B2 12), 0 eliminadas, 0 skip/xfail añadidos
```

Las 28 pruebas nuevas se ejecutaron también sobre el árbol reconstruido por el parche, con el
mismo resultado. Las pruebas de concurrencia de M1 (hilos y multiproceso) y los límites
transaccionales del experimento 03 siguen verdes después de cambiar el camino de append.

---

## O. Riesgos residuales (explícitos)

| riesgo | estado | nota |
|---|---|---|
| **Sin raíz de confianza**: una reescritura completa y coherente del store, o un rollback de `CURRENT`, no se detectan | abierto, declarado en `SECURITY.md` | requiere firma por versión + ancla externa del head: cambio de formato y de gestión de claves, fuera de alcance |
| El *append* no revalida la cadena completa | contrato nuevo, documentado | los lectores siguen fallando cerrado; nada inválido se escribe (§M, `SECURITY.md`) |
| Búsqueda de versión ausente en el índice: lineal en el número de versiones | medido, acotado (§C.7) | eliminarlo exige formato nuevo |
| Commit lineal en el tamaño del grafo (validación de esquema + re-verificación de blobs) | inherente al modelo, medido (§C.6) | no se cambió ninguna garantía para mejorarlo |
| `flock` no es fiable en sistemas de archivos de red | abierto | el lock es local; no se usa para coordinar máquinas |
| Sin prueba de corte de energía / `fsync` a nivel de dispositivo | abierto | backup en el mismo disco = copia lógica, no dominio de fallo separado |
| `runtime/memory_canonical` sigue siendo una segunda autoridad hasta la integración | abierto | decisión de reemplazo vs convivencia pendiente (§L) |
| Los 18 campos perdidos por la proyección paralela no están enumerados | abierto | exige leer el esquema y el adaptador reales |
| `KuyenMemory.restore` no sobrescribe un store existente (por diseño) | contrato | mover un store es decisión del operador, no efecto secundario |

---

## P. Criterios de aceptación

| criterio | estado | evidencia |
|---|---|---|
| M6 corregido o cerrado con evidencia | **corregido** | §C, banco antes/después, 0 lecturas completas por commit |
| B1 corregido, recuperación idempotente | **sí** | §D, 8 pruebas, `verify()` correcto |
| B2 corregido sin destruir destinos | **sí** | §E, 12 pruebas, instantáneas intactas |
| A1–A3, M1–M5, B3, límites del exp. 03 siguen pasando | **sí** | §N.3, suite verde |
| M7 corregido | **sí** | §F, entorno limpio con `.[dev]` |
| B5 corregido y mínimo demostrado | **sí** | §G, 77.0.1 construye, 76.1.0 no |
| Wheel y sdist construidos e inspeccionados | **sí** | §H |
| Metadatos y dependencias coherentes | **sí** | §M |
| Instalación limpia de wheel y de sdist | **sí** | §I.1, §I.2 |
| Import desde `site-packages`, `pip check`, sin `PYTHONPATH` | **sí** | §I.1–I.2 |
| Ciclo funcional completo, offsets, hashes, versiones | **sí** | §I.3 |
| Backup, restore, recuperación y reconstrucción | **sí** | §I.3 |
| Resultados equivalentes entre wheel y sdist | **sí** | 38 claves, 0 diferencias |
| Independencia de OpenViking y LLM | **sí** | §J |
| Parche reproducible y árbol reconstruido idéntico | **sí** | §N.1 |
| Informes y parches anteriores intactos | **sí** | §A, `evidence/00_baseline_identity.txt` |
| Entrega: informe, artefactos, hashes, manifiesto, pruebas, matriz, riesgos | **sí** | este informe + `release_candidate_05/` |

```
VEREDICTO FINAL: RELEASE_CANDIDATE_PASS
```

Los artefactos están listos para revisión y para una decisión de publicación que **no** se ha
tomado aquí. La etapa siguiente (`LEFTRARU_KUYEN_RUNTIME_INTEGRATION_01`) puede instalarlos
en un entorno aislado de LeftraruOS y demostrar que KÜYEN es la única autoridad de memoria.
