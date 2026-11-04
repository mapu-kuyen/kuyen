# KUYEN_SOURCE_UNIT_DISAMBIGUATION_03

**Objeto:** resolución de `SOURCE_UNIT` por identificador en el paquete público `kuyen`.
**Workspace:** `/tmp/kuyen_hardening_01/kuyen` (candidato `0.2.1rc1`, HEAD `5fd8777a8305097792380fceb9ff861de208147a`, HEAD *detached*).
**Ejecución:** 2026-11-02, de `22:25Z` a `22:38Z`.
**Origen del hallazgo:** `KUYEN_RELEASE_QUICKSTART_REPAIR_02`, §6 (límite 1).

```
VEREDICTO: SOURCE_UNIT_DISAMBIGUATION_PASS
```

Ninguna evidencia puede ya resolver en silencio una unidad perteneciente a otro MAPU: la
resolución está contextualizada por el documento, la consulta sin contexto rechaza la
ambigüedad en lugar de devolver la primera coincidencia, y el flujo real de evidencia
(`trace`) verifica MAPU, span, hash de unidad y cita en sus offsets antes de devolver nada.
21 pruebas adversariales nuevas, suite **365 tests · 363 passed · 0 failed · 2 skipped**
(referencia 344 · 342 · 2) y las cuatro combinaciones wheel/sdist × 3.11/3.13 en verde.

---

## 1. Identidad y preservación

| dato | valor |
|---|---|
| HEAD / rama | `5fd8777a8305097792380fceb9ff861de208147a` · `HEAD` (detached) |
| `VERSION` | `0.2.1rc1` (intacto: `9f286730…b376b3`) |
| `pyproject.toml` | intacto (`7cef38e9…461bf0`) |
| Cambios preexistentes | 24 archivos modificados + 26 entradas no rastreadas (hardening 01–05 + reparación del Quickstart + documentos), preservados |
| Quickstart 02 | `source_uris` presente (3 ocurrencias); `tests/examples/` y `scripts/verify_distribution.py` intactos (`202f3671…`, `91aac3e7…`, `eff22c8a…`) |
| Hardening 01–05 | `validate_canonical_objects`, `_reject_unsafe_target`, `classify_staging`, `source_bytes_sha256`, `iter_lines_reverse` presentes |
| Entradas nuevas de este experimento | `M src/kuyen/errors.py`, `M tests/…` → nuevo `tests/test_source_unit_disambiguation.py`; `M api/memory.py`, `M PUBLIC_API.md`, `M DATA_MODEL.md` (estos tres ya estaban modificados/no rastreados) |
| Sin `reset`/`checkout`/`clean` | no se ejecutó ninguno; el árbol no se reconstruyó desde `5fd8777` |


---

## 2. Contrato: ¿`unit_id` es global o local?

**Es local a su MAPU.** No se asumió: se verificó contra el modelo, el código y el uso real.

| evidencia | qué dice |
|---|---|
| `DATA_MODEL.md` §SOURCE_UNIT | «A passage of a MAPU: `unit_id`, `mapu_id`, …» — el identificador aparece **dentro** de una unidad que ya declara su MAPU |
| estructura persistida de la unidad | todo registro de `source_units` lleva `unit_id` **y** `mapu_id`; el `unit_id` solo nunca identifica un registro |
| `sidecar/exporter.py::_source_units` | construye unidades **por MAPU**; `u00` es el valor natural del primer unit de cada documento |
| camino Antü (`lifecycle/antu.py::_merge`) | añade `instruction["unit"]` (que incluye `mapu_id`) al inventario; nadie comprueba unicidad global |
| `PUBLIC_API.md` (antes) | «One SOURCE_UNIT with its verified text slice» — sin declarar el alcance, que es justo lo que ocultaba el defecto |
| uso real | el Quickstart (02) y cualquier memoria con dos documentos producen dos `u00` sin que nada los rechace |
| ningún validador | ni A1 ni el validador tipado exigen unicidad global de `unit_id` |

Conclusión: la identidad de una unidad es el par **`(mapu_id, unit_id)`**. La implementación
anterior resolvía por la mitad del par y devolvía la primera coincidencia.

### Call graph (calculado sobre el árbol actual)

```
DEFINICIÓN
  src/kuyen/api/memory.py::KuyenMemory.source_unit(unit_id, version_id=None, *, mapu_id=None)

RESOLUCIÓN DE UNA UNIDAD A PARTIR DE UNA EVIDENCIA
  api/memory.py::trace(claim_id)        -> _evidence_unit(sidecar, evidence, mapus)
  api/memory.py::_evidence_unit         -> verifica MAPU + span + hash de unidad + cita
  api/memory.py::_select_source_unit    -> selecciona por (mapu_id, unit_id), o falla
  api/memory.py::evidence_of(claim_id)  -> devuelve evidencias (no resuelve unidades)

CONSUMIDORES DE `source_unit()` (antes del cambio)
  src/kuyen/…                            -> NINGUNO (ningún camino interno lo llamaba)
  tests/api/test_public_api.py           -> memory.source_unit("u00")
  tests/examples/test_quickstart_example.py -> memory.source_unit(item["source_unit_id"])
  /Users/…/leftraruOS/runtime, tests      -> NINGUNO (grep vacío)
  documentación                          -> PUBLIC_API.md, QUICKSTART.md

OTROS LUGARES QUE AGRUPAN UNIDADES (no resuelven, pero nombran unidades por id)
  storage/commit.py::_object_hashes       -> hashes["source_units/<unit_id>"]
  sidecar/__init__.py::build_sidecar      -> source_hashes.source_units[<unit_id>]
  projection/mapping.py                   -> conjuntos {unit_id}
  validation/validators.py                -> comprobaciones de cobertura por unidad
```

Que **ningún camino interno** llamara a `source_unit()` explica por qué el defecto sobrevivió:
solo lo alcanzaba un usuario externo que, después de `trace()`, pidiera la unidad por su id.

---

## 3. Reproducción (antes / después)

Mismo store, misma consulta, dos implementaciones. «Antes» se ejecutó contra el paquete
**instalado** en el venv del runtime (`0.2.1rc1` sin el cambio, en `site-packages`), que es
código real no modificado; «después», contra el árbol corregido.

```
=== ANTES ===
evidence mapu/unit: MAPU-DEMO-02 u00
unscoped lookup   : returned MAPU MAPU-DEMO-01 | WRONG DOCUMENT: True
scoped lookup     : TypeError -> source_unit() got an unexpected keyword argument 'mapu_id'

=== DESPUÉS ===
evidence mapu/unit: MAPU-DEMO-02 u00
unscoped lookup   : refused -> AmbiguousSourceUnit | SOURCE_UNIT u00 exists in 2 MAPUs (MAPU-DEMO-01, MAPU-DEMO-02)
scoped lookup     : MAPU MAPU-DEMO-02 | slice matches quote: True
```

Logs: `logs/03_before_reproduction.log`, `logs/04_after_reproduction.log`.

Efecto colateral medido y **no corregido** (fuera de alcance): en ese mismo store la colisión
hace que `source_hashes.source_units` y `object_hashes["source_units/<id>"]` conserven **una
sola** entrada `u00` (gana la última). No oculta manipulación —el sidecar está direccionado
por contenido y `verify()` detecta una edición coherente del mismo— pero el mapa no puede
nombrar ambas unidades. Ver §8.


---

## 4. Corrección

Cinco archivos; ningún formato persistente, esquema, mecanismo de commit ni validador cambió.

### 4.1 Contrato nuevo (público)

```python
memory.source_unit(unit_id, version_id=None, *, mapu_id=None) -> dict
```

| situación | antes | ahora |
|---|---|---|
| `mapu_id` dado y el par existe | no existía el parámetro | devuelve **esa** unidad, verificada |
| `mapu_id` dado y el MAPU no existe | — | `StoreError` (`unknown MAPU …`) |
| `mapu_id` dado y el MAPU no tiene esa unidad | — | `StoreError` (`MAPU … has no SOURCE_UNIT …`) |
| sin `mapu_id`, una sola coincidencia | devolvía la unidad | **igual** (compatibilidad, caso C) |
| sin `mapu_id`, varias coincidencias | devolvía la **primera** (defecto) | `AmbiguousSourceUnit` con `details.candidates` |
| sin `mapu_id`, ninguna coincidencia | `StoreError` | `StoreError` (mensaje distingue versión) |

`AmbiguousSourceUnit` es pública, documentada y hereda de `StoreError`, con
`code = "AMBIGUOUS_SOURCE_UNIT"`: cualquier consumidor que ya capturaba `StoreError` sigue
fallando en cerrado sin cambios.

### 4.2 Resolución de evidencia (el flujo real)

`trace()` ya no «busca» una unidad: la **resuelve y la verifica** con `_evidence_unit`, que
rechaza explícitamente

1. un `mapu_id` que la versión no contiene;
2. offsets no utilizables (`char_start`/`char_end` ausentes o invertidos);
3. una evidencia cuyo span no está contenido en **ninguna** unidad de su MAPU;
4. un span cubierto por más de una unidad (`AmbiguousSourceUnit`);
5. una unidad cuyo `content` no coincide con su `content_sha256`;
6. una cita que no coincide con el texto en sus offsets;
7. un `source_sha256` que no es el hash del MAPU citado.

Nunca se considera una unidad de otro MAPU: el conjunto de candidatos se filtra por
`mapu_id` **antes** de mirar spans. El resultado de `trace()` gana
`source_unit_mapu_id` (aditivo) para que el consumidor pueda comprobar por sí mismo que la
unidad pertenece al documento de la evidencia.

### 4.3 Qué NO se tocó

`src/kuyen/validation/` (A1 intacto), el mecanismo de commit, los esquemas, los formatos
persistentes, el adaptador de LeftraruOS, CI, README, CHANGELOG, SECURITY.md, `VERSION` y
`pyproject.toml`.

---

## 5. Casos adversariales (`tests/test_source_unit_disambiguation.py`, 21 pruebas)

| caso | prueba | resultado |
|---|---|---|
| **A** ids locales repetidos | `TestScopedResolution` (3) | `source_unit("u00", mapu_id="MAPU-B")` devuelve MAPU-B; `trace` informa `source_unit_mapu_id == mapu_id` y el slice coincide |
| **B** consulta sin contexto y ambigua | `TestUnscopedLookup` (3) | rechazo explícito con `code == AMBIGUOUS_SOURCE_UNIT` y `candidates == ["MAPU-A", "MAPU-B"]`; nunca la primera coincidencia; sigue siendo `StoreError` |
| **C** compatibilidad sin colisión | `TestUniqueIdentifierCompatibility` (3) | `source_unit("u01")` sin contexto sigue funcionando; también con contexto; memoria de un solo documento sin cambios |
| **D** MAPU incorrecto | `TestWrongMapu` (3) | `u01` pedido en MAPU-A → `StoreError`; MAPU inexistente → `StoreError`; id inexistente → `StoreError`. Nunca sustitución |
| **E** evidencia cruzada | `TestEvidenceChainVerification` (8, comprobación que ejecuta `trace`) | unidad de otro MAPU → rechazo; MAPU desconocido → rechazo; cita incompatible con offsets → rechazo; hash de unidad incoherente → rechazo; span fuera de toda unidad → rechazo; `source_sha256` de otro documento → rechazo; store manipulado → rechazo y `verify() == False`; control positivo correcto |
| **F** independencia del orden | `TestOrderIndependence` (1) | con MAPU-A primero y con MAPU-B primero: mismas resoluciones por MAPU y **misma** ambigüedad, con candidatos ordenados (nunca el orden de inserción) |
| **G** regresión del Quickstart | `TestQuickstartRegression` (1) | el ejemplo se ejecuta en subproceso fuera del repositorio, `verify: ok=True`, y cada evidencia resuelve a una unidad de su propio MAPU con la cita en sus offsets |

Ningún `skip`, `xfail` ni prueba anterior modificada. El caso E incluye una prueba de caja
blanca sobre `_evidence_unit` (la misma función que usa `trace`) porque una evidencia cruzada
**no puede** persistirse: A1 la rechaza en el commit; el lector debe fallar en cerrado ante un
store ya dañado, y eso es lo que se demuestra.


---

## 6. Compatibilidad pública

| consumidor | uso | efecto |
|---|---|---|
| usuarios que llaman `source_unit(unit_id)` en memorias de **un** documento | caso válido más común | **sin cambios** |
| usuarios con dos documentos y `unit_id` únicos | caso válido | **sin cambios** (caso C) |
| usuarios con `unit_id` repetidos y sin `mapu_id` | recibían silenciosamente el documento equivocado | ahora `AmbiguousSourceUnit`; hay que pasar `mapu_id` (una línea) |
| usuarios que capturaban `StoreError` | — | la nueva excepción hereda de `StoreError`: el manejo existente sigue valiendo |
| `trace()` | devolvía `source_unit_id` (y `None` si no había unidad) | ahora **verifica** y lanza en lugar de devolver `None` o un id ambiguo; añade `source_unit_mapu_id` (aditivo) |
| LeftraruOS (`runtime/`, `tests/`) | no usa `source_unit` ni `trace` | sin impacto |
| firma | `source_unit(unit_id, version_id=None)` | `mapu_id` es *keyword-only* con defecto `None`: ninguna llamada posicional se rompe |

Se documentó el nuevo contexto en `PUBLIC_API.md` (firma, ambigüedad, excepciones y garantía 4)
y el alcance de la identidad en `DATA_MODEL.md`. No se conservó ninguna conducta insegura por
compatibilidad: la consulta ambigua ya no devuelve nada.

---

## 7. Regresión

| comprobación | referencia | ahora |
|---|---|---|
| suite completa | 344 tests · 342 passed · 2 skipped | **365 · 363 · 2** (+21 nuevas, 0 eliminadas, 0 `skip`/`xfail`) |
| pruebas de ambigüedad | — | 21/21 |
| pruebas de memoria y evidencia (`tests/api`) | verdes | verdes |
| A1 y procedencia (`test_a1_canonical_validation`, `test_source_provenance`) | verdes | verdes |
| Quickstart (`tests/examples` + caso G) | 5 verdes | verdes |
| wheel · 3.11 / 3.13 | PASS | **PASS** |
| sdist · 3.11 / 3.13 | PASS | **PASS** |
| 18 campos (LeftraruOS) | 43 passed | **43 passed** |
| `SHA256SUMS` de `release_candidate_05` | 27/27 | **27/27** (`016871c4…3d8e`) |
| `pip check` (venv del runtime) | limpio | **limpio** |
| `RECORD` del paquete instalado | 103/103 | **103/103** |
| LeftraruOS `git status` | 204 | **204** (HEAD `fb5c311` sin cambios) |

Artefactos construidos desde el candidato corregido:

| artefacto | bytes | sha256 |
|---|---|---|
| `kuyen-0.2.1rc1-py3-none-any.whl` | 220 877 | `d862f9df0ae0c11b156c733adc627d80b6dbd664191ec8b8e17371f78fc3c956` |
| `kuyen-0.2.1rc1.tar.gz` | 204 775 | `77032d33d9cbc03db7508dc5bc98294ae7ff91ed1d92930da64c16ad0ef3561e` |

En las cuatro combinaciones el import vino de `site-packages` (nunca del repositorio), el
ejemplo salió con código 0, sin `EVIDENCE_URI_MISMATCH`, con dos versiones comprometidas y
`verify()` correcto. Una primera ejecución del verificador falló en `wheel/3.11` porque se
lanzó en paralelo con la construcción (el wheel aún no existía); se repitió en secuencia y
las cuatro pasaron. Queda registrado para no confundirlo con un fallo del producto.

---

## 8. Límites restantes

1. **Mapas persistidos que nombran unidades solo por `unit_id`** (no corregido; cambiar la
   clave altera el formato persistido, prohibido en este experimento):
   `sidecar.source_hashes.source_units` y `manifest.object_hashes["source_units/<id>"]`
   colapsan cuando dos MAPU comparten `unit_id`. Medido: una sola entrada `u00`. No crea una
   vía de sustitución de procedencia y la manipulación sigue detectándose (el sidecar está
   direccionado por contenido; `verify()` devolvió `False` con una edición coherente), pero el
   registro no puede enumerar ambas unidades. **Recomendación:** en un experimento propio,
   versionar el formato y clavar la clave en `(mapu_id, unit_id)`.
2. **Cobertura de la prueba de caja blanca**: el caso E verifica el resolutor directamente
   porque una evidencia cruzada no puede persistirse (A1 la rechaza). El camino público está
   cubierto por los casos A, B, C, D, F y G.
3. **`projection/mapping.py`** agrupa unidades por `unit_id` en conjuntos; con colisiones el
   mapeo de correspondencia puede perder una referencia. Es proyección (regenerable), no
   procedencia canónica; no se tocó y no se midió su efecto.
4. **Documentación del Quickstart**: sigue sin mencionar que `execute_antu(mapu_source=…)`
   recibe una ruta (hallazgo de 02, fuera de alcance aquí).
5. **CI y publicación**: sin cambios. No se corrigió CI, no se consolidó la release y no se
   publicó nada.

---

## 9. Entregables

| ubicación | contenido |
|---|---|
| `docs/KUYEN_SOURCE_UNIT_DISAMBIGUATION_03.md` | este informe |
| `experiments/KUYEN_SOURCE_UNIT_DISAMBIGUATION_03/` | estado Git inicial/final, hashes, call graph, contrato, tabla de casos, `before/` y `after/`, logs (build, suite, distribución, integración, antes/después), JSON de distribución, patch, `MANIFEST.json` |
| `src/kuyen/api/memory.py` | `source_unit(..., *, mapu_id=None)`, `_select_source_unit`, `_evidence_unit`, `trace` verificado |
| `src/kuyen/errors.py` | `AmbiguousSourceUnit` |
| `PUBLIC_API.md`, `DATA_MODEL.md` | contrato y alcance de `unit_id` |
| `tests/test_source_unit_disambiguation.py` | 21 pruebas adversariales |
| `/tmp/kuyen_source_unit_disambiguation_03/` | evidencia operativa completa (artefactos, logs, JSON, patch) |

**Patch reproducible:** `source_unit_disambiguation_03.patch` (`aae031e3…2359`, 614 líneas,
5 archivos). Se validó reconstruyendo el estado **anterior** desde el paquete instalado
(`memory.py`, `errors.py`) y el sdist de 02 (`PUBLIC_API.md`, `DATA_MODEL.md`), comprobando
que los cuatro hashes coinciden con el manifiesto inicial, aplicando el patch y verificando que
los cinco archivos resultantes tienen exactamente los hashes del árbol actual.

**No se hizo:** commit, tag, push, publicación, ni cambios en CI, README, CHANGELOG,
SECURITY.md, `VERSION`, `pyproject.toml`, esquemas, formatos persistentes, A1,
mecanismo de commit o adaptador de LeftraruOS.

**Se detiene aquí.** No se inicia la corrección de CI ni la consolidación de la release.

Hashes iniciales y finales en `experiments/KUYEN_SOURCE_UNIT_DISAMBIGUATION_03/`.
