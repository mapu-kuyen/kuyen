# KUYEN_RELEASE_QUICKSTART_REPAIR_02

**Objeto:** `examples/quickstart.py` del paquete público `kuyen`.
**Workspace:** `/tmp/kuyen_hardening_01/kuyen` (candidato `0.2.1rc1`, HEAD `5fd8777a8305097792380fceb9ff861de208147a`, HEAD *detached*).
**Ejecución:** 2026-11-02, de `22:02Z` a `22:18Z`.
**Referencia:** `KUYEN_PUBLIC_RELEASE_READINESS_AUDIT_01` (`/tmp/kuyen_public_release_readiness_audit_01/`).

```
VEREDICTO: QUICKSTART_DISTRIBUTION_PASS
```

El ejemplo público funciona en las cuatro combinaciones exigidas (wheel y sdist × Python 3.11 y 3.13),
desde un directorio fuera del repositorio, importando el paquete instalado, sin `EVIDENCE_URI_MISMATCH`,
con dos versiones comprometidas, evidencia recuperada hasta el texto de origen y `verify() == True`.
La regresión queda automatizada (5 pruebas nuevas) y la suite no presenta regresiones: **344 tests,
342 passed, 0 failed, 2 skipped** frente a la referencia **337 passed, 2 skipped**.

---

## 1. Identidad y preservación

| dato | valor |
|---|---|
| HEAD / rama | `5fd8777a8305097792380fceb9ff861de208147a` · `HEAD` (detached), tag `v0.2.0` |
| `VERSION` | `0.2.1rc1` (intacto: `9f286730…b376b3`) |
| `pyproject.toml` | intacto (`7cef38e9…461bf0`) — **no se modificó** |
| Cambios previos | 23 archivos modificados + 23 entradas no rastreadas (hardening 01–05), intactos |
| Hardening verificado | `validate_canonical_objects`, `_reject_unsafe_target`, `classify_staging`, `source_bytes_sha256`, `iter_lines_reverse` presentes; hashes de `src/kuyen/*` idénticos al inicio y al final |
| Estado final del árbol | exactamente **4 entradas nuevas** respecto del inicial: ` M examples/quickstart.py`, `?? tests/examples/`, `?? scripts/`, `?? experiments/` (evidencia) |
| `src/kuyen/` | **sin cambios** (13 modificados + 2 no rastreados, igual que al inicio) |
| Sin `reset`/`checkout`/`clean` | no se ejecutó ninguno; no se limpió ni reconstruyó el workspace |

---

## 2. Diagnóstico del defecto

**Síntoma.** `examples/quickstart.py` terminaba con:

```
kuyen.errors.CommitError: EVIDENCE_URI_MISMATCH: ev_ee8250fb76e094b34b47 cites a different source_uri than its MAPU
```

**Cadena causal, verificada en el código:**

1. La regla A1 vive en `src/kuyen/validation/canonical.py` y exige igualdad estricta:
   `declared_uri != mapu["source_uri"]` → `EVIDENCE_URI_MISMATCH` (la ruta tipada,
   `validation/validators.py`, aplica la misma igualdad desde antes).
2. `src/kuyen/ingest.py::build_document` asigna a cada MAPU
   `source_uris.get(mapu_id, f"viking://resources/{mapu_id}")`.
3. El ejemplo declaraba `uri = "viking://resources/demo/MAPU-DEMO-01.txt"` en la evidencia,
   en la cobertura y en `coverage_inventory`, pero llamaba
   `build_document(demo_graph(), {MAPU_ID: SOURCE})` **sin** `source_uris`.
4. Resultado: el MAPU quedaba registrado como `viking://resources/MAPU-DEMO-01` y la evidencia citaba
   `viking://resources/demo/MAPU-DEMO-01.txt`. Dos identidades para el mismo documento.
5. En 0.2.0 ese camino no ejecutaba la validación A1, así que la incoherencia se aceptaba en silencio:
   el ejemplo "funcionaba" y el store quedaba con una procedencia inconsistente.

**No era un defecto del núcleo.** La regla es correcta y debe permanecer: una evidencia que cita un
documento distinto del que la memoria guarda es exactamente lo que el producto promete detectar.

---

## 3. Corrección aplicada

Archivos (solo estos tres; `src/kuyen/`, `pyproject.toml`, `VERSION`, `README`, `CHANGELOG`,
`SECURITY.md`, CI y adaptadores **no se tocaron**):

| archivo | cambio |
|---|---|
| `examples/quickstart.py` | reescrito: declara `source_uris` y demuestra el ciclo completo (10 pasos) |
| `tests/examples/test_quickstart_example.py` | **nuevo**: 5 pruebas de regresión |
| `scripts/verify_distribution.py` | **nuevo**: verificador reproducible de wheel y sdist (fuera de la suite) |

**La corrección mínima era una palabra clave** — `source_uris={MAPU_ID: uri}` — pero el ejemplo, además,
no demostraba el camino de escritura que `QUICKSTART.md` documenta. Se completó sin cambiar la API:

* el URI se declara **una vez** por documento y se reutiliza en `mapu`, `evidence`, `coverage`,
  `coverage_inventory` y `source_uris`, de modo que la identidad no puede divergir;
* se añade un Antü real sobre un segundo MAPU: `execute_antu(...)` → `VALIDATED` → `commit(...)` →
  versión `1.1.0` con padre;
* la procedencia se demuestra de punta a punta: afirmación → evidencia → `SOURCE_UNIT` → texto,
  comprobando la cita en sus offsets y el hash del MAPU;
* se conserva el backup/restore y se añade `recover_from_store` (reconstrucción sólo desde el store);
* el ejemplo **no** usa APIs privadas, no accede a estructuras internas, no desactiva A1 y no omite
  evidencia: si la cita no coincide con el texto en sus offsets, el propio ejemplo falla.

**Contrato de demostración (§4 del encargo), línea por línea de la salida:**

| paso | salida del ejemplo |
|---|---|
| 1. inicializar memoria | `memory created at …/memory` |
| 2. ingresar MAPU con URI de origen | `committed MAPU-DEMO-01 as VER-e95aa365324f (kuyen 1.0.0)` |
| 3-4. conocimiento estructurado + evidencia del documento | dentro del documento canónico y del Antü |
| 5. validar el Antü | `Antü ANTU-DEMO-0002: VALIDATED (nothing written yet)` |
| 6. confirmar nueva versión | `committed VER-152e1ad799b7 (kuyen 1.1.0), parent VER-e95aa365324f` |
| 7. consultar el grafo | `graph: 3 entities, 1 relations, 1 assertions, 2 evidence records` |
| 8. localizar la afirmación | `claim asrt_b33e90e83cb4df3acb1c: 1200 cajas (2024)` |
| 9. recuperar evidencia y procedencia | `provenance: 'exporto 1.200 cajas a Brasil'` · `at 28:56 of MAPU-DEMO-02 <viking://…/MAPU-DEMO-02.txt>` · `sha256 2a8a26a7…` |
| 10. verificación de integridad | `verify: ok=True problems=[]` |

Sin red, sin modelo, sin OpenViking, sin credenciales. Los identificadores son deterministas: las
mismas versiones (`VER-e95aa365324f`, `VER-152e1ad799b7`) se obtienen en los cuatro entornos.

---

## 4. Verificación de distribución (obligatoria)

Artefactos construidos desde el candidato corregido con `python -m build` (build 1.6.1, setuptools
84.2.1, aislamiento por defecto):

| artefacto | bytes | sha256 |
|---|---|---|
| `kuyen-0.2.1rc1-py3-none-any.whl` | 219 027 | `e22612792dfe9655e01e78bef4b51de78922f28cb4e0ca3cc107cfb40052cd83` |
| `kuyen-0.2.1rc1.tar.gz` | 202 590 | `7ebc0d51d00975e39dce041b39b80e919c161f32ce348a97bec9b82e2eb1dd63` |

Cuatro entornos virtuales independientes y limpios (`python -m venv`, sin `PYTHONPATH`), el ejemplo
copiado **fuera** del repositorio y ejecutado desde allí:

| combinación | intérprete | instala | `pip check` | salida | `EVIDENCE_URI_MISMATCH` | versiones | `verify()` | URI evidencia == URI MAPU | import desde |
|---|---|---|---|---|---|---|---|---|---|
| wheel · 3.11 | 3.11.15 | OK | limpio | **0** | no | 2 | `True` | sí | `site-packages` |
| wheel · 3.13 | 3.13.1 | OK | limpio | **0** | no | 2 | `True` | sí | `site-packages` |
| sdist · 3.11 | 3.11.15 | OK | limpio | **0** | no | 2 | `True` | sí | `site-packages` |
| sdist · 3.13 | 3.13.1 | OK | limpio | **0** | no | 2 | `True` | sí | `site-packages` |

`all_passed=True`, `skipped=[]`. En las cuatro, `kuyen.__file__` cae dentro del `venv` y la ruta del
repositorio **no** aparece en la ruta de importación. Evidencia: `logs/31_{wheel,sdist}-py{3.11,3.13}.log`,
`30_distribution_verification.json`, `logs/30_distribution_verification.log`.

Reproducible con:

```bash
python scripts/verify_distribution.py \
  --no-build \
  --wheel  dist/kuyen-0.2.1rc1-py3-none-any.whl \
  --sdist  dist/kuyen-0.2.1rc1.tar.gz \
  --python 3.11 --python 3.13 \
  --json-out report.json
```


---

## 5. Regresión automatizada y del paquete

### 5.1 Prueba nueva (unitarias + ejecución real del ejemplo)

`tests/examples/test_quickstart_example.py` — 5 pruebas, todas ejecutan el ejemplo como un usuario
(subproceso, `cwd` fuera del repositorio) y luego comprueban el contrato con la API pública:

| prueba | qué impide que vuelva a ocurrir |
|---|---|
| `test_it_exits_zero_without_the_uri_mismatch` | el ejemplo debe terminar en 0 y no emitir `EVIDENCE_URI_MISMATCH` |
| `test_it_reports_a_validated_antu_and_a_verified_memory` | la salida debe mostrar `VALIDATED`, `verify: ok=True` y reconstrucción aceptada |
| `test_it_commits_two_versions_that_verify` | dos versiones, con padre, e `verify()` correcto |
| `test_every_evidence_cites_the_source_uri_of_its_own_mapu` | **el contrato de procedencia**: cada evidencia cita exactamente el `source_uri` de su MAPU (no compara texto impreso) |
| `test_each_claim_resolves_to_its_quote_in_the_source` | cada afirmación resuelve a una `SOURCE_UNIT` **del mismo MAPU** y la cita coincide en sus offsets |

Si alguien elimina `source_uris` del ejemplo, la primera y la tercera prueba fallan inmediatamente.

### 5.2 Verificador de distribución (fuera de la suite)

`scripts/verify_distribution.py` construye (o recibe) wheel y sdist, instala cada uno en un venv
desechable con el intérprete pedido, ejecuta el ejemplo desde fuera del repositorio, comprueba
`pip check`, que el import venga de `site-packages` y el contrato de procedencia, y devuelve 0 solo si
todo pasa. **No** forma parte de la suite: una construcción completa por ejecución haría la suite lenta
y dependiente del entorno.

### 5.3 Suite completa

| referencia (auditoría) | ahora | diferencia |
|---|---|---|
| 339 tests · 337 passed · 0 failed · 2 skipped | **344 tests · 342 passed · 0 failed · 2 skipped** | +5 pruebas nuevas, 0 eliminadas, 0 `skip`/`xfail` añadidos |

Los 2 `skipped` siguen siendo los preexistentes y autoexcluyentes (integración real con OpenViking;
fixture de investigación no distribuido). Ninguna prueba previa se modificó para obtener verde.

### 5.4 Integridad del paquete y de los hardening

| comprobación | resultado |
|---|---|
| Hardening 01–05 | `src/kuyen/*` con hashes idénticos al inicio; 17 archivos de prueba de hardening verdes dentro de la suite |
| 18 campos (LeftraruOS) | `43 passed` en `tests/test_kuyen_integration.py`, `test_single_authority.py`, `test_canonical_source_provenance.py` (incluye `missing == []`, `mismatched == []`) |
| KÜYEN instalado en el runtime | `0.2.1rc1` desde `site-packages`, **no reinstalado ni modificado**; `RECORD` verificado: 103 entradas con hash, **0 discrepancias** |
| 27/27 hashes | `shasum -a 256 -c SHA256SUMS.txt` en `release_candidate_05` → **27/27 OK**, archivo `016871c4…3d8e` (sin cambios) |
| `pip check` | limpio en el venv del runtime |
| Repositorio LeftraruOS | `git status --porcelain` **204 → 204**; HEAD `fb5c311` sin cambios |
| `src/kuyen/`, `pyproject.toml`, `VERSION` | sin cambios (hashes iniciales == finales) |


---

## 6. Límites encontrados

1. **`memory.source_unit(unit_id)` es ambiguo entre MAPUs** (hallazgo nuevo, **no corregido**: fuera de
   alcance). `source_unit()` devuelve la primera unidad cuyo `unit_id` coincide, sin filtrar por MAPU.
   Reproducido: dos documentos que usan `unit_id = "u00"` (el valor natural) hacen que, para una
   evidencia de `MAPU-DEMO-02`, `source_unit("u00")` devuelva la unidad de `MAPU-DEMO-01` — documento
   equivocado, en silencio. Rompe la promesa "cada afirmación llega a su texto de origen" en memorias
   con más de un documento. El ejemplo lo evita usando `u01` para el segundo documento (los `unit_id`
   son únicos dentro de una versión) y la prueba nueva verifica que la unidad resuelta pertenece al
   MAPU de la evidencia. **Recomendación:** corregir la firma pública en un experimento propio
   (p. ej. `source_unit(unit_id, *, mapu_id=None)`), con prueba de regresión para ids repetidos.
2. **El ejemplo no se distribuye**: `examples/quickstart.py` no está ni en el wheel ni en el sdist
   (`MANIFEST.in` sólo incluye `*.md` de la raíz). El verificador copia el archivo desde el repositorio,
   de modo que la comprobación es válida, pero un usuario que sólo instala el paquete **no recibe el
   ejemplo**. No se tocó el empaquetado porque el encargo lo restringe y no es necesario para las
   cuatro combinaciones; queda como limitación de adopción ya registrada en la auditoría.
3. **`mapu_source` es una ruta, no texto**: el ejemplo ahora lo demuestra escribiendo el documento en
   disco, pero `README.md`/`PUBLIC_API.md` siguen sin decirlo (documentación fuera de alcance).
4. **`ProvenanceError`** (fuente inexistente) no figura en la lista de excepciones públicas documentadas.
5. **CI y publicación**: sin cambios. La CI seguirá en rojo por causas ajenas a este experimento (job de
   higiene que importa sin instalar). No se corrigió CI, no se consolidó la release y no se publicó nada.
6. **Alcance del ejemplo**: cubre la API pública de memoria (crear, ingestar, validar, comprometer,
   leer, rastrear, respaldar, restaurar, recuperar, verificar). No cubre proyecciones, reconciliación
   ni el adaptador OpenViking, deliberadamente fuera del "primer ejemplo".

---

## 7. Entregables

| ubicación | contenido |
|---|---|
| `docs/KUYEN_RELEASE_QUICKSTART_REPAIR_02.md` | este informe (en el repositorio, como los informes de hardening) |
| `experiments/KUYEN_RELEASE_QUICKSTART_REPAIR_02/` | estado Git inicial/final, hashes, `before/` y `after/`, logs de build, de cada instalación y ejecución, JSON de verificación, patch |
| `examples/quickstart.py` | ejemplo corregido (modificado) |
| `tests/examples/test_quickstart_example.py` | regresión (nuevo) |
| `scripts/verify_distribution.py` | verificador de wheel/sdist (nuevo) |
| `/tmp/kuyen_release_quickstart_repair_02/` | evidencia completa: `dist/` con los dos artefactos, `logs/`, `evidence/`, `before/`, `after/`, `quickstart_repair_02.patch` |
| `/tmp/kuyen_release_quickstart_repair_02/quickstart_repair_02.patch` | patch reproducible (`645db7f0…707b`, 706 líneas) que aplica sobre `5fd8777` con `git apply --check` y `patch -p1` |

**No se hizo:** commit, tag, push, publicación, instalación en el runtime, ni cambios en `src/kuyen/`,
`pyproject.toml`, `VERSION`, README, CHANGELOG, SECURITY.md, CI o adaptadores.

**Se detiene aquí.** No se corrige CI, no se consolida la release y no se publica.

El defecto era del ejemplo, y su causa inmediata es que **ninguna prueba lo ejecutaba**.
