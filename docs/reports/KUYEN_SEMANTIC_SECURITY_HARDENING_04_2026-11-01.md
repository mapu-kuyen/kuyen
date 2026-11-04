# KUYEN_SEMANTIC_SECURITY_HARDENING_04 — Informe de ejecución

**Paquete:** `kuyen` 0.2.0 · **Commit base:** `5fd8777a8305097792380fceb9ff861de208147a`
**Workspace:** `/tmp/kuyen_hardening_01/kuyen` (working tree con A1–A3, M1–M2 y los límites
transaccionales de los experimentos 01, 02 y 03)
**Fecha:** 2026-11-01 (UTC-3)
**Veredicto:** **PASS** para M3, M4, M5 y B3 · sin empaquetado, publicación ni integración con
LeftraruOS

---

## A. Identidad y estado

| dato | valor |
|---|---|
| ruta | `/tmp/kuyen_hardening_01/kuyen` |
| HEAD | `5fd8777a8305097792380fceb9ff861de208147a` — **sin cambios al inicio y al final** |
| rama | `HEAD` (detached) |
| `VERSION` | `0.2.0` (sin tocar) |
| Python | 3.13.1 · `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3` |
| import | `kuyen.__file__` = `/private/tmp/kuyen_hardening_01/kuyen/src/kuyen/__init__.py` (vía `PYTHONPATH=src`) |
| entorno | sin instalaciones, sin credenciales, sin variables de red |
| estado Git inicial | 10 modificados + 13 entradas no rastreadas (A1–A3, M1–M2, exp. 03 y sus informes) |
| estado Git final | **17 modificados** (se añaden `ingest.py`, `storage/registry.py`, `storage/versions.py`, los cuatro documentos) + **19 entradas no rastreadas** (se añaden `src/kuyen/provenance.py`, `tests/security/`, `test_antu_contract.py`, `test_source_provenance.py`, `test_reconciliation_metadata.py` y este informe) |
| commits / índice | **ninguno** / intacto (no se usó `git add`, ni `reset`, ni `clean`, ni `checkout`) |

### Artefactos previos (hash al inicio y al final: idénticos)

| artefacto | sha256 |
|---|---|
| `hardening.patch` (01) | `6ce8914303c77e73391f21991ed8e228bd85fc91e52bf275526e0bcd90ce3d33` |
| `ledger_recovery_hardening_02.patch` (02) | `67bc04b2f619067f6e5c794b8cde980c2ab1f01738e548698b69abb196bbdade` |
| `transaction_boundary_hardening_03.patch` (03) | `7d6ea6ded6af5ecbfe21d9dce1527c5c15946d615432605ecedc2c1db3fb9273` |
| `KUYEN_PACKAGE_HARDENING_01_2026-11-01.md` | presente, sin sobrescribir |
| `KUYEN_LEDGER_RECOVERY_HARDENING_02_2026-11-01.md` | presente, sin sobrescribir |
| `KUYEN_TRANSACTION_BOUNDARY_HARDENING_03_2026-11-01.md` | presente, sin sobrescribir |

Correcciones previas verificadas como presentes antes de tocar código: `validate_canonical_objects`
(A1), `_require_expected_base` (A2), `_reject_unsafe_target` (A3), `_write_operation` (M1),
`read_classified`/`repair_ledger` (M2), `claim` de outbox y `reconcile_unit_history` (exp. 03),
`temporary_name` con secuencia+urandom (exp. 03).

### Línea base reproducida (no asumida)

```
PYTHONPATH=src python3 -m pytest -q --junitxml=baseline_04/10_suite_before.xml
→ 252 tests · 250 passed · 0 failed · 0 errors · 2 skipped · 5,0 s
PYTHONPATH=src python3 -m pytest -q --cov=kuyen
→ cobertura 77 % (7 829 sentencias, 1 797 sin cubrir)
```

Coincide con la referencia del experimento 03. Los 2 `skipped` son los preexistentes
(integración real con OpenViking, `KUYEN_RUN_OPENVIKING` sin definir).

### Reproducción previa a toda corrección

Se construyó un *worktree* limpio en el commit base, se aplicaron los tres parches anteriores
(los tres aplican sin conflicto) y se copiaron allí las pruebas nuevas: **39 de las 59 pruebas
nuevas fallan** en el estado previo, una por frente.

```
git worktree add /tmp/kuy04/before 5fd8777a… --detach
cd /tmp/kuy04/before && git apply hardening.patch ledger_recovery_hardening_02.patch transaction_boundary_hardening_03.patch
PYTHONPATH=src python3 -m pytest -q tests/security tests/lifecycle/test_antu_contract.py tests/lifecycle/test_source_provenance.py
→ 39 failed · 36 passed
   tests/lifecycle/test_source_provenance.py  16 failed
   tests/lifecycle/test_antu_contract.py      11 failed
   tests/security/test_tamper_detection.py     9 failed
   tests/security/test_version_id_containment.py 3 failed
```

Evidencia en `/tmp/kuyen_hardening_01/baseline_04/30_reproduction_before_fix.log` y
`31_signatures.log`. Firmas del estado previo:

| frente | firma observada |
|---|---|
| B3 | `read_version(store, '../../decoy')` **devuelve** el manifiesto señuelo; `DID NOT RAISE StoreError` en ruta relativa, absoluta y symlink |
| M3 | `verify()` → `True` con `counts` y `object_hashes` manipulados (`AssertionError: undetected manifest tampering: {'counts': {'entities': 99}}`) |
| M4 | `build_document` guarda `sha256` = hash del texto normalizado, no de los bytes del CRLF; `execute_antu` con fuente CRLF y hash correcto de los bytes → `REJECTED` (`declared MAPU hash does not match the provided source`) |
| M5 | `KeyError: 'mapu_id'` desde `api/memory.py:320`; `KeyError: 'entity_id'` desde `_verify_proposal`; `VALIDATED` seguido de `CommitError` en `commit` |

---
## B. M3 — detección de manipulación

### B.1 Qué declaraba `SECURITY.md` y qué demostraba el código

`SECURITY.md:26-27` afirmaba: *«Tamper detection: manifests, sidecar, ledger chain, index,
CURRENT and backups are hash-checked»*. La inspección de los mecanismos mostró una asimetría:
todo lo demás estaba atado por un hash, pero **el manifiesto no lo estaba a nada propio**.

| mecanismo | qué hashea | qué verifica |
|---|---|---|
| blobs | nombre = SHA-256 del contenido | cada lectura re-hashea (`get_blob`) |
| ledger | `event_hash` sobre el cuerpo + `prev_event_hash` | `verify_chain` recalcula la cadena |
| índice | entrada por versión | `verify_registry` compara hash con el manifiesto |
| CURRENT | puntero con `canonical_graph_hash` | `verify_registry` compara con el manifiesto |
| sidecar | `integrity.sidecar_content_hash` | `verify_sidecar` + comparación con el manifiesto |
| integridad | `integrity_id` sobre sí mismo | **nadie lo leía en `verify_version`** |
| manifiesto | **nada** | — |

`verify_version` sólo comprobaba que los blobs referenciados existieran y coincidieran con su
hash, y dos campos del sidecar. Consecuencia reproducida: cambiar en `manifest.json` `counts`,
`object_hashes`, `parent_version_id`, `antu_id` o `kuyen_version` dejaba `verify()` en `True`.

### B.2 Causa raíz

El manifiesto se publicaba como autoridad pero **ningún registro independiente lo cubría**, y
sus campos derivados (versión, identidad, inventario de objetos) no se contrastaban contra los
registros que sí son *content-addressed*: el blob `KUYEN_CANONICAL_VERSION_INTEGRITY` (que
contiene `objects`, `object_count`, `sidecar_sha256`, `mapping_sha256`,
`projection_manifest_sha256`, `canonical_graph_hash`, `kuyen_id`, `kuyen_version` e
`integrity_id`) y el propio sidecar. Además, `verify()` resumía el fallo de una versión como
`«version X failed verification»`, sin el motivo: un reporte de seguridad tiene que decir qué
artefacto falló.

### B.3 Corrección

`storage/versions.py` incorpora tres verificadores y los usa en `verify_version`:

```
_identity_problems(manifest)      version_id == version_id_for(identity_core)
                                  kuyen_id/kuyen_version/canonical_graph_hash/
                                  parent_version_id/antu_id/unit_revision == identity_core
_integrity_problems(manifest, i)  i.objects == object_hashes, i.object_count == len(...)
                                  i.{sidecar,mapping,projection_manifest}_sha256 == blobs
                                  i.kuyen_id/kuyen_version/canonical_graph_hash == manifiesto
                                  integrity_id == digest(integridad sin integrity_id)
_sidecar                             ids, canonical_graph_hash, sidecar_content_hash,
                                  object_counts == counts
+                                    version_id del manifiesto == nombre de su directorio
```

`api/memory.py::verify()` ahora devuelve, por versión, `{version_id, ok, problems}` y agrega
esos problemas al reporte global. La verificación es **más estricta**, nunca más laxa: no se
relajó ningún control previo y no se añadió ningún `skip`.

### B.4 Matriz real de detección (probada)

| cambio | detectado | por |
|---|---|---|
| blob corrupto | sí | nombre = hash, re-hash en lectura |
| blob borrado | sí | `missing blob` + problema por versión |
| `counts` del manifiesto | **sí (antes no)** | `sidecar.object_counts` |
| `object_hashes` vaciado | **sí (antes no)** | `integrity.objects`/`object_count` |
| `canonical_graph_hash` | sí (antes sí) | sidecar + integridad + identidad |
| `sidecar_content_hash` | sí (antes sí) | sidecar |
| `parent_version_id` / `antu_id` / `kuyen_version` | **sí (antes no)** | `identity_core` |
| manifiesto copiado a otro directorio de versión | **sí (antes no)** | `version_id` ≠ directorio y ≠ `identity_core` |
| un evento del ledger editado | sí | `event_hash`/`prev_event_hash` |
| versión inexistente | sí | `StoreError` controlado |
| **cadena de eventos reescrita completa** | **no** | la cadena es autoconsistente: falta anclaje |
| **versión reemplazada con todos sus registros** | **no** | falta raíz de confianza |
| **rollback de `CURRENT` a otra versión válida** | **no** | el puntero coincide con ese manifiesto |
| **metadatos fuera del store** | **no** | no forman parte del store |

`SECURITY.md` se reescribió para declarar exactamente esta tabla, incluida la sección *Limits of
tamper detection*, que dice sin rodeos que **no hay firma, MAC ni ancla externa** y que quien
pueda reescribir todo el store consistentemente produce un store que verifica. Las dos pruebas
de la clase `TestDocumentedLimits` fijan ese límite: si algún día se detecta, la documentación
obligatoriamente cambia con ellas.

### B.5 Propuesta no implementada (cambio de formato + raíz de confianza)

Cerrar los tres huecos exige un ancla fuera del store:

1. **Firma por versión**: `manifest.signature` (Ed25519) sobre `canonical_json` del manifiesto
   sin el campo `signature`; la clave pública vive fuera del store (variable de entorno,
   `~/.config/kuyen/trusted_keys.json` o KMS). Rompe `schema_version` del manifiesto → requiere
   migración y queda fuera de este experimento.
2. **Ancla de la cabeza del ledger**: publicar periódicamente `(seq, head_hash)` en un destino
   externo de sólo-append (log WORM, OTRO store, ticket). Detecta la reescritura de la cadena.
3. **Anti-rollback**: `pointer_generation` monótona ya existe, pero nada externo la fija; una
   atestación externa de la generación mínima cierra el rollback.

Ninguna se implementa aquí por la restricción explícita de no introducir formatos persistidos ni
raíces de confianza sin aprobación.

---

## C. M4 — fuentes CRLF, hashes y offsets

### C.1 Flujo reconstruido

```
archivo --(1)--> bytes --(2)--> texto --(3)--> unidades (offsets) --(4)--> MAPU/SOURCE_UNIT
                                                                          |
                              (5) verificación de evidencia (quote en char_start..char_end)
```

En el estado previo: (1) `execute_antu` usaba `Path(mapu_source).read_text()`, que traduce
`\r\n`→`\n` (universal newlines) y por tanto **nunca veía los bytes**; (2) `build_document`
hasheaba el *string* que recibía (`sha256_text`), no los bytes del archivo. Los offsets eran —y
siguen siendo— **puntos de código Unicode sobre el texto decodificado**, pero esa convención no
estaba declarada en el registro, y el hash declarado se confundía con el hash del archivo.

### C.2 Dos síntomas reproducidos

| síntoma | evidencia |
|---|---|
| **procedencia silenciosamente falsa** | archivo CRLF con bytes `3384934f…` guardado con `mapu.sha256 = fd97c713…`, que es el hash de su imagen LF. La memoria dice «esta es la fuente» y señala un hash que no corresponde al archivo |
| **fuente CRLF imposible de incorporar** | con `mapu.sha256` = hash correcto de los bytes (`3c9c0b0c…`), `execute_antu` → `REJECTED: declared MAPU hash does not match the provided source`, porque el texto leído ya había perdido los `\r` |

No basta con conservar el fragmento ni con hashear una representación normalizada sin decir cuál:
una evidencia tiene que poder reconstruirse **y comprobarse** contra la fuente original.

### C.3 Política aplicada

Se distingue explícitamente tres identidades, sin tocar los campos existentes:

| campo (nuevo, aditivo) | significado |
|---|---|
| `source_bytes_sha256` | SHA-256 de los **bytes originales** del archivo |
| `content_sha256` (existente) | SHA-256 del **texto decodificado**, que es lo que direccionan los offsets |
| `encoding` | codificación declarada (`utf-8` por defecto) |
| `newline_policy` | `PRESERVED` (bytes preservados) o `UNKNOWN` (sólo se recibió texto) |
| `offset_unit` | `unicode_codepoint` (la convención de `Evidence`) |
| `source_hash_scope` | `SOURCE_BYTES` o `DECODED_TEXT`: qué está hasheando el registro |
| `source_bytes` | tamaño de los bytes originales |

Invariante que hace la correspondencia comprobable: **`content.encode(encoding) == bytes
originales`**. `build_document` la verifica y falla con `ExportError` si el llamador pasa bytes
que no decodifican al texto declarado; no se «repara» nada en silencio.

`kuyen/provenance.py` (nuevo) expone:

```python
read_source(path, *, encoding="utf-8") -> SourceText     # bytes + decodificación estricta
                                                          # sin traducción de saltos de línea
decode_source(data, *, encoding, source_uri) -> SourceText
SourceText.to_record() -> dict                            # los campos de procedencia
```

`execute_antu` lee con `read_source`, acepta un `sha256` declarado que coincida con **los bytes o
con el texto** (registrando `declared_sha256_matches`) y persiste los campos de procedencia en el
registro del MAPU.

### C.4 Pruebas (17)

`tests/lifecycle/test_source_provenance.py`:

* seis fixtures — LF, CRLF, CR, Unicode multibyte (`ñandú 日本語 🚀`), saltos combinados, y un
  fragmento que empieza y termina en salto de línea — verifican que `source_bytes_sha256` es el
  hash de los bytes, que `content` re-codifica a esos bytes, que `content_sha256` es el hash del
  texto y que `content[char_start:char_end]` es exactamente la cita;
* cada fixture se importa, se verifica (`verify()`), se respalda y se restaura, comprobando que la
  procedencia sobrevive al ciclo;
* bytes que no decodifican al texto declarado → `ExportError`;
* documento sin bytes → `source_hash_scope = DECODED_TEXT` y `newline_policy = UNKNOWN`
  (no se finge un hash de archivo);
* fuente vacía → registro de procedencia válido con `sha256("")`, sin unidades y sin evidencia;
* fuente CRLF por el camino Antü → `VALIDATED`, se confirma, y el MAPU fusionado conserva
  `source_bytes_sha256`, `newline_policy = PRESERVED` y `content.encode() == bytes`;
* hash declarado de otro archivo → `REJECTED`.

---
## D. M5 — ciclo de vida ANTÜ y estado `VALIDATED`

### D.1 Ciclo inspeccionado

```
recepción → parseo → estructura → identidad/evidencia/contrato → preparación de la propuesta
          → VALIDATED → (commit) validación de documento + sidecar → publicación → revisión
          → proyección → recuperación
```

### D.2 Dos causas raíz

**(1) `KeyError` accidental.** `_verify_proposal` construía conjuntos con `entity["entity_id"]` e
`item["evidence_id"]`, `execute_antu` usaba `declaration["mapu_id"]` e
`instruction["unit"]["unit_id"]`, y `_merge` usaba `instruction["unit"]` y `instruction["coverage"]`.
Un Antü sin `mapu`, sin `unit`, sin `proposal` o con entidades sin id lanzaba `KeyError` **después**
de haber escrito `ANTU_RECEIVED`: quedaba un recibo colgado, sin rechazo registrado y con una
excepción no tipada escapando de la API pública.

**(2) `VALIDATED` no implicaba las precondiciones del commit.** `execute_antu` sólo ejecutaba la
verificación de la propuesta; la validación del *documento resultante* y la verificación del
sidecar ocurrían por primera vez dentro de `commit_version`. Reproducido: un `entity_id` con
formato inválido (`ent_short`) o una unidad cuyo `content_sha256` no coincide con su contenido se
presentaban como `VALIDATED` y fallaban en `commit` con `CommitError`.

### D.3 Corrección

1. `lifecycle/antu.py::validate_antu_structure(antu) -> list[str]`: validador **total** (nunca
   lanza) de `antu_id`, `kind` (conjunto cerrado), `base_version_id`/`leftraru_id`/`purpose`
   tipados, `mapu.{mapu_id,source_uri,sha256}`, `unit.{unit_id,mapu_id,char_*,chars}`,
   coherencia `unit.mapu_id == mapu.mapu_id`, `coverage` objeto y `proposal.{entities,relations,
   assertions,evidence}` listas de objetos.
2. `execute_antu` y `lifecycle.antu.execute` lo ejecutan **antes de escribir nada**; si hay
   problemas y el Antü trae un `antu_id` usable, se registra `ANTU_REJECTED` con `reasons` y se
   lanza `ValidationRejected("ANTU_STRUCTURE_INVALID: …", report={"problems": [...]})` (error
   tipado, con detalle trazable).
3. `_verify_proposal` es total: `.get()` en los conjuntos de ids propuestos.
4. `storage/commit.py::prepare_commit_artifacts(document, ...)` extrae el paso 1–2 del commit
   (`_validate` + proyección + mapping + sidecar + `verify_sidecar`) y lo usan **los dos**: el
   commit (autoridad) y `execute_antu` antes de declarar `VALIDATED`. Un defecto de contrato es
   ahora un `REJECTED`, no una sorpresa posterior.

### D.4 Contrato de estados (sin estados nuevos)

| situación | representación | efecto en el store |
|---|---|---|
| Antü inválido (estructura) | `ValidationRejected` + `ANTU_REJECTED` si hay `antu_id` | ninguno |
| Antü inválido (identidad, evidencia, contrato, esquema del documento resultante) | `AntuExecution(status="REJECTED", detail={"reasons"})` | evento `ANTU_REJECTED` |
| Antü válido y preparado | `VALIDATED` (pasa ya la validación del commit) | eventos de recepción |
| base obsoleta | `CONFLICT` (`STALE_BASE`) | `ANTU_REJECTED` |
| commit rechazado por conflicto concurrente | `StoreError` (CAS de `CURRENT`, A2) | nada; la ejecución sigue `VALIDATED` |
| commit fallido por error operacional (I/O) | excepción del sistema | nada; la ejecución sigue `VALIDATED` y es reintentable |
| commit completado | `COMMITTED` | versión + revisión + outbox |
| interrupción tras publicar | `verify()` lo reporta, `pending()` lo lista, `recover()` lo repara con procedencia | `RECONCILIATION` |

Se documentó en `ANTU_LIFECYCLE.md` (estado `VALIDATED` + sección *VALIDATED is not COMMITTED*).
No se añadió ningún estado ni migración: el contrato existente expresa las diferencias.

### D.5 Pruebas (16)

`tests/lifecycle/test_antu_contract.py`: 10 Antüs mal formados (vacío, sólo id, sin `unit`, sin
`proposal`, `mapu`/`proposal` con tipo incorrecto, `entities` no lista, `antu_id` no string, `kind`
desconocido, `base_version_id` no string) → `ValidationRejected` con `report["problems"]`, store
intacto y `verify()` OK; rechazo registrado en el ledger con `reasons`; identificadores inválidos →
`REJECTED` (nunca `VALIDATED`); unidad con hash incoherente → `REJECTED` (antes: `VALIDATED` +
`CommitError`); Antü válido → `VALIDATED` + `COMMITTED`; dos Antüs validados desde la misma base
→ el segundo commit falla con `StoreError`, no publica nada, no registra revisión y no se presenta
como completado; fallo de I/O simulado tras validar → nada cambia y el commit es reintentable.

---

## E. B3 — seguridad de `version_id`

### E.1 Causa raíz

`storage/versions.py` construía `store.versions_dir / version_id / "manifest.json"` con la cadena
recibida **sin validar**. Reproducido: con un señuelo en `<tmp>/outside/manifest.json`,
`read_version(store, '../../decoy')` y `read_version(store, '/ruta/absoluta/decoy')` **devolvían
el manifiesto señuelo**. Afectaba a todas las rutas públicas que terminan en `read_version`:
`graph`, `sidecar`, `source_unit`, `evidence_of`, `trace`, `lineage`, `verify_version`,
`verify_commit`, proyección nativa, recuperación, `children`, `by_antu`. Además
`storage/registry.py::lineage` construía una ruta desde `parent_version_id` del manifiesto y
`store.write_current` desde el `version_id` de `CURRENT`.

### E.2 Corrección

```python
VERSION_ID_RE = re.compile(r"^VER-[0-9a-f]{12}$")
validate_version_id(ident)          # tipo y formato antes de construir cualquier ruta
version_manifest_path(store, ident) # resuelve y exige que el destino siga bajo <store>/versions
```

`version_manifest_path` compara la ruta **resuelta** (`Path.resolve`, que sigue symlinks) contra
la raíz resuelta de versiones: rechaza `..`, rutas absolutas, separadores y un directorio de
versión que sea un enlace simbólico hacia fuera. Se aplica en `read_version`, `write_version`,
`verify_version` y, vía `read_version`, en toda la API pública. `registry.lineage` ya no construye
rutas desde datos del manifiesto y `write_current` valida el `version_id` del puntero antes de
escribir `refs/history/<id>.json`.

### E.3 Pruebas (7)

`tests/security/test_version_id_containment.py`: `..`, `../`, `../../`, `../..`, `.../.../`,
relativa al señuelo, absoluta, `/etc`, `/etc/passwd`, separadores (`a/b`, `a\b`), componentes
vacíos (`""`, `" "`, `"."`, `"~"`), id válido con `/` final, symlink a un directorio externo,
id bien formado pero inexistente, y un control positivo con el id real. En todos los casos
negativos se comprueba que `read_version`, `verify_version`, `lineage`, `graph`, `sidecar` y
`lineage` de la API lanzan `StoreError`, que el señuelo **no** se lee y que `CURRENT` no cambia.

---
## F. Revisión de las garantías del experimento 03

Los cuatro riesgos señalados se inspeccionaron sin reabrir su implementación, salvo el segundo,
que resultó ser un defecto demostrable y se corrigió aquí.

### F.1 Evento `RECONCILIATION` usado para reparar revisiones — **A (aceptable)**

Un consumidor puede distinguir una reparación de una operación ordinaria por metadatos
declarados, sin inferirla del orden: el evento es de tipo `RECONCILIATION` (nunca
`ANTU_COMPLETED`), lleva `reason="PUBLISHED_VERSION_WITHOUT_REVISION"` y el `version_id`
reparado; la revisión sintetizada lleva `detail.recovered = true`, `detail.reason`,
`detail.recovered_from = versions/<id>/manifest.json`, `detail.assigned_unit_revision`,
`detail.manifest_unit_revision` y `detail.reconciled_at`. Una revisión ordinaria no tiene
`detail.recovered`.

`tests/lifecycle/test_reconciliation_metadata.py` (2 pruebas) fija esa distinción: una revisión
reparada es autodescriptiva y el import ordinario nunca aparece como reparación.

### F.2 Temporales abandonados e inertes — **B, corregido en este paso**

Inertes para los lectores (nadie abre `manifest.json.tmp-…`, `blob_path` exige 64 hex), pero
`store.verify_objects()` hasheaba **todo** archivo bajo `objects/` y exigía que su nombre fuera su
hash. Reproducido: tras un «crash» que deja `.tmp-…` en `objects/sha256/ab/`, `verify()` devolvía
`False` con `HASH_MISMATCH` — un store sano presentado como corrupto, y `verify()` es la puerta de
`backup`, `restore` y de los informes de integridad.

Corrección mínima (sin reescribir el componente): los nombres que empiezan por `.tmp-` se cuentan
como `ignored_temporaries` y se ignoran; cualquier **otro** archivo cuyo nombre no sea una
dirección de contenido se reporta como `UNEXPECTED_FILE` (antes se confundía con
`HASH_MISMATCH`). Un archivo ajeno en `objects/` sigue siendo un problema; un temporal de una
escritura interrumpida, no. Pruebas: `TestCrashLeftovers` (2).

### F.3 Coordinación entre procesos en backups — **A (aceptable)**

`create_backup` copia el store sin el lock de escritura. Se midió el caso en un experimento
dedicado (no forma parte de la suite, dura ~40 s): **10 commits concurrentes + 20 backups**.

| resultado | n |
|---|---|
| backup copiado y `verify_backup` OK, y el store restaurado verifica | 18 |
| backup rechazado por `verify_backup` (copia desgarrada detectada: `index references a missing version`) | 1 |
| backup interrumpido por la carrera de `shutil.copytree` (error controlado; el `backup` siguiente borra el destino parcial) | 1 |
| **backup sellado que restaure un store incoherente** | **0** |
| store origen al final | `verify()` OK |

El sellado + `verify_backup` (que incluye la verificación de registro) impiden que una copia
desgarrada se presente como buena: falla en cerrado. Recomendación para una etapa posterior
(fuera de alcance): tomar la copia bajo un lock de lectura compartido, o reintentar el backup ante
`FileExistsError` de la carrera.

### F.4 I/O externo fuera del lock — **A (aceptable)**

`project()` reclama, publica y completa cada operación bajo `writer_lock` y ejecuta las llamadas
al motor **fuera** del lock (diseño de outbox, ya verificado en el experimento 03). `commit` no
hace E/S de red. Observación nueva de esta pasada: `execute_antu` ejecuta ahora
`prepare_commit_artifacts` (validación + proyección + sidecar, sólo CPU) **dentro** del lock de
escritura del método; no añade E/S externa pero alarga la sección crítica — relevante para M6
(escalabilidad del commit), no para la corrección.

---

## G. Validación integral

### G.1 Pruebas focalizadas

| conjunto | pruebas | resultado |
|---|---|---|
| M3 `tests/security/test_tamper_detection.py` | 17 | 17 passed |
| M4 `tests/lifecycle/test_source_provenance.py` | 17 | 17 passed |
| M5 `tests/lifecycle/test_antu_contract.py` | 16 | 16 passed |
| B3 `tests/security/test_version_id_containment.py` | 7 | 7 passed |
| revisión exp. 03 `tests/lifecycle/test_reconciliation_metadata.py` | 2 | 2 passed |

### G.2 Sin regresiones

```
tests/api/test_a1_canonical_validation.py           OK
tests/storage/test_a2_stale_base_commit.py          OK
tests/storage/test_a3_backup_target.py              OK
tests/lifecycle/test_m1_ledger_concurrency.py       OK
tests/lifecycle/test_m1_ledger_multiprocess.py      OK
tests/lifecycle/test_m2_ledger_recovery.py          OK
tests/lifecycle/test_m1_m2_combined.py              OK
tests/lifecycle/test_operation_boundary.py          OK
tests/projection/, tests/storage/test_atomic_write_boundary.py   OK
```

### G.3 Suite completa y cobertura

```
PYTHONPATH=src python3 -m pytest -q --junitxml=baseline_04/21_suite_after.xml
→ 311 tests · 309 passed · 0 failed · 0 errors · 2 skipped · 6,6 s
   (252 de línea base + 59 nuevas, 0 eliminadas, 0 `skip`/`xfail` añadidos)

PYTHONPATH=src python3 -m pytest -q --cov=kuyen
→ cobertura 78 % (8 029 sentencias, 1 787 sin cubrir)   [antes: 77 %, 7 829 / 1 797]
```

### G.4 Revisión del diff y de los artefactos

| comprobación | resultado |
|---|---|
| archivos tocados en esta pasada | 17: 4 documentos, 8 fuentes (`api/memory.py`, `ingest.py`, `lifecycle/antu.py`, `storage/{commit,registry,store,versions}.py`, `provenance.py` nuevo), 5 archivos de prueba |
| tamaño | +1 777 / −61 líneas en 18 archivos (17 + este informe) |
| eliminaciones no intencionadas | ninguna (revisadas todas las líneas `-`) |
| parches previos | los tres aplican sin conflicto sobre `5fd8777a…` y su hash no cambió |
| reproducibilidad | `base + 3 parches` == estado previo de esta pasada (mismo `git status`); `base + 3 parches + este parche` == workspace, con `diff -ruN` vacío y `git apply` sin avisos |
| commits / índice / `VERSION` | ninguno / intacto / `0.2.0` |
| repos ajenos | `knowledge/kuyen` 0.1.9, `leftraru-os`, `leftraru-cl`, `leftraru-lft`: no tocados |
| stores reales | no tocados; toda prueba destructiva bajo `tmp_path`/`/tmp` con verificación de ruta |

---

## H. Compatibilidad, contratos y límites

### H.1 Compatibilidad con stores existentes

| cambio | efecto en un store ya escrito |
|---|---|
| campos nuevos del MAPU (`source_bytes_sha256`, `source_hash_scope`, `encoding`, `newline_policy`, `offset_unit`, `source_bytes`) | **ninguno**: son opcionales; un registro sin ellos se interpreta como `DECODED_TEXT` |
| `verify_version`/`verify()` más estrictos | un store íntegro sigue verificando; cualquier store que hoy pase y no cumpla las nuevas comprobaciones estaba inconsistente (no se ha encontrado ninguno en la suite) |
| `validate_version_id` / `version_manifest_path` | sólo rechaza identificadores que antes producían lectura fuera del store |
| `verify_objects` ignora `.tmp-*` | un store con temporales de un crash pasa a verificar (antes: falso positivo); un archivo ajeno sigue reportado |
| `VALIDATED` más estricto | un Antü que antes llegaba a `VALIDATED` y fallaba en `commit` ahora se rechaza antes; el contrato se documentó |
| manifiestos, sidecar, ledger, índice, formato de blobs | **sin cambios de formato** |

No se modificó `VERSION` (0.2.0), ni `schema_version` de ningún artefacto persistido, ni se añadió
dependencia alguna.

### H.2 Contratos públicos afectados

| contrato | cambio |
|---|---|
| `build_document(...)` | nuevos keywords opcionales `source_bytes`, `encodings`; nueva `ExportError` si los bytes no decodifican al texto |
| `kuyen.provenance` | módulo nuevo (`read_source`, `decode_source`, `SourceText`, `ProvenanceError`) |
| `KuyenMemory.execute_antu` | puede lanzar `ValidationRejected` con `report["problems"]`; puede devolver `REJECTED` donde antes devolvía `VALIDATED` |
| `KuyenMemory.verify()` | cada entrada de `versions` incluye `problems`; los problemas se agregan con prefijo `version <id>:` |
| `verify_version` / `read_version` / `write_version` | `StoreError` para identificadores inválidos o rutas que escapan del store |
| `store.verify_objects()` | nuevo contador `ignored_temporaries`; nuevo problema `UNEXPECTED_FILE` |
| `storage.commit.prepare_commit_artifacts` | función nueva (extracción del paso 1–2 de `commit_version`) |

### H.3 Garantías que siguen limitadas

1. **Sin raíz de confianza** (M3): una reescritura completa y coherente del store no es
detectable. Requiere firma por versión + ancla externa del ledger (propuesta en B.5), lo que
implica formato persistido nuevo y gestión de claves.
2. **Anti-rollback**: `CURRENT` puede devolverse a una versión anterior válida sin que `verify()`
lo note; `pointer_generation` existe pero no está anclada externamente.
3. **M6 escalabilidad del commit**: la validación completa + proyección + sidecar (y ahora también
en `execute_antu`) corren dentro del lock de escritura global.
4. **B1 `recover_pending` y B2 restore sobre directorio existente**: sin cambios en esta pasada;
`restore` sigue rechazando un destino no vacío (falla en cerrado, no sobrescribe).
5. **Acoplamiento con `runtime/memory_canonical`**: sigue sin decidirse (el adaptador de LeftraruOS
es *vendored*, declarado con pérdida, y `leftraru-os` no importa `kuyen`).
6. **Fuentes sin bytes**: si el llamador sólo aporta texto, KÜYEN declara el alcance
(`DECODED_TEXT`) pero no puede probar la correspondencia con el archivo original, porque nunca lo
vio.

### H.4 Riesgos residuales

| riesgo | severidad | estado |
|---|---|---|
| reescritura coherente total del store | alta pero **fuera del modelo de amenaza** (el store es del operador) | declarado en `SECURITY.md`; mitigación propuesta |
| backup tomado durante un commit falla y hay que repetirlo | baja | clasificado A; recomendación anotada |
| sección crítica más larga en `execute_antu` | baja | anotado para M6 |
| `verify()` más estricto puede sorprender a un consumidor que ignoraba `problems` | baja | documentado en H.2 |

---

## I. Veredicto

| criterio de aceptación | resultado |
|---|---|
| **M3**: implementación y documentación no se contradicen | **cumple** — `SECURITY.md` declara la matriz real, con los tres huecos explícitos; 13 pruebas de detección + 2 que fijan el límite |
| **M4**: hashes y offsets permiten verificar LF, CRLF y Unicode | **cumple** — `source_bytes_sha256` + decodificación sin traducción + `content.encode() == bytes`; 17 pruebas con 7 fixtures, backup/restore incluidos |
| **M5**: ningún Antü inválido llega a `VALIDATED`; los fallos se representan | **cumple** — validador estructural total, rechazos registrados, `VALIDATED` = precondiciones del commit satisfechas; 16 pruebas |
| **B3**: ninguna API pública lee fuera del store por `version_id` | **cumple** — formato + contención resuelta + symlinks; 7 pruebas con señuelos fuera del store |
| A1–A3, M1–M2 y límites del experimento 03 sin regresiones | **cumple** — subconjuntos verdes |
| suite completa ejecutada | **cumple** — 311 tests, 309 passed, 0 failed, 2 skipped, 78 % |
| sin pérdida de datos ni cambios persistidos incompatibles | **cumple** — sólo campos aditivos opcionales; ningún formato reescrito |

**Veredicto: PASS.**

Las cuatro garantías auditadas se alinearon con lo que el código demuestra. Donde la arquitectura
no puede demostrar más —no hay raíz de confianza—, la documentación lo declara y las pruebas lo
fijan, en lugar de prometerlo.

### Siguiente paso recomendado (no ejecutado)

1. Cerrar los huecos restantes de la lista de la auditoría antes de integrar: **M6** (escalabilidad
del commit: escritura de objetos y validación completa bajo un lock global), **B1**
(`recover_pending`) y **B2** (restore sobre directorio existente).
2. Decidir el acoplamiento con `runtime/memory_canonical` (reemplazo vs convivencia) y sólo
después construir el candidato instalable de KÜYEN y validarlo desde LeftraruOS en un entorno
aislado.
3. Si el producto necesita garantías frente a un operador hostil, aprobar el esquema de firma +
ancla externa descrito en B.5 antes de congelar el formato.

---

## Entregables

| entregable | ruta |
|---|---|
| este informe | `docs/reports/KUYEN_SEMANTIC_SECURITY_HARDENING_04_2026-11-01.md` (no rastreado) |
| parche incremental | `/tmp/kuyen_hardening_01/semantic_security_hardening_04.patch` |
| parches anteriores (intactos) | `/tmp/kuyen_hardening_01/{hardening,ledger_recovery_hardening_02,transaction_boundary_hardening_03}.patch` |
| evidencia | `/tmp/kuyen_hardening_01/baseline_04/` (identidad, `git status` antes, hashes de parches, suite antes/después, cobertura, reproducción sin el fix, firmas) |
