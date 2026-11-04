# KUYEN_ANTU_OPERATIONAL_COVERAGE_15

**Veredicto.** Las operaciones que quedaban sin demostrar existen, funcionan con el modelo real y
quedan versionadas sobre las diez memorias del experimento 13, sin recompilar ningún documento y
sin cambiar de modelo:

* **se incorporó una relación** entre dos entidades existentes de KUYEN-004 y la versión la
  registra con procedencia `ANTU_INSTRUCTION` y sin evidencia documental inventada;
* **se actualizó una entidad** (`UPDATE_ENTITY`) conservando identidad, relaciones, atributos,
  evidencia y la versión anterior legible;
* **se actualizó un atributo** tipado (`UPDATE_ATTRIBUTE`), declarado primero en el esquema y
  corregido después, sin crear ninguna afirmación;
* **una instrucción larga con tres cambios** se confirmó en una sola versión de KUYEN-005
  (campo de esquema + atributo + relación);
* la causa real del `NO_CHANGES` sistemático del experimento 14 **no era el modelo**: era que
  KÜYEN buscaba `operations` en la raíz y el modelo las anidaba dentro de `contract`, imitando el
  sobre de la petición. Con el normalizador corregido, la misma instrucción larga produce dos y
  tres operaciones válidas;
* una respuesta sin operaciones y sin explicación ya **no** se registra como «no hay cambios»:
  es `INTERPRETATION_INCOMPLETE` (`EXECUTION_FAILED`), y cada resultado distingue
  `COMMITTED`, `ALREADY_SATISFIED`, `NEEDS_CLARIFICATION`, `INVALID_PROPOSAL`, etc.

* rama: `work/kuyen-free-text-graph` · HEAD inicial y final de código: `b6a00d0`
* evaluaciones reales: 14 (2 antes de la corrección del normalizador, 12 después)
* confirmadas: 6 · ya satisfechas: 1 · aclaración: 1 · rechazadas: 4 · incompletas: 0 tras la
  corrección
* coste verificado por la respuesta del proveedor: **$0.112531 USD** (308 573 tokens de entrada,
  16 632 de salida)
* versiones: 23 al empezar → 28 al cerrar (KUYEN-004 1→5, KUYEN-005 4→5; las otras ocho memorias
  intactas)

## 1. Estado del repositorio

| dato | valor |
| --- | --- |
| raíz | `/private/tmp/kuyen_hardening_01/kuyen` |
| rama | `work/kuyen-free-text-graph` |
| HEAD inicial | `b6a00d0` (sin commits nuevos al empezar) |
| HEAD de código al cerrar | `a6bc996` (pruebas `951b1ba`, documentación `e85d95b`, manifiesto `54ce6e7`) |
| trabajo previo | intacto: **71** entradas en `git status` al empezar y **69** al cerrar (las dos que faltan son `editing/operations.py` y `editing/service.py`, que se confirman con este experimento; su trabajo previo va descrito en el mensaje del commit `d565f00`) |
| archivos del experimento | 23: 9 modificados y 14 nuevos (código, pruebas y 12 artefactos del experimento; el manifiesto no se hashea a sí mismo) |
| OpenViking | **no ejecutado**; ninguna compilación documental repetida |
| documentos | ningún MAPU reprocesado; ninguna memoria recreada |

La comprobación de que el trabajo previo no se tocó está en
`evidence/state_before.json` y `evidence/state_after.json`: los 703 archivos de los experimentos
13 y 14 tienen el mismo SHA-256 en ambos estados.

## 2. Causas identificadas

| # | síntoma | causa encontrada | corrección |
| --- | --- | --- | --- |
| 1 | el modelo devolvía `NO_CHANGES` en instrucciones largas (exp. 13 y 14) | el modelo responde `{"status":…,"contract":{"operations":[…]}}`, imitando el sobre de la petición; KÜYEN sólo leía `operations` en la raíz y veía una propuesta vacía | el normalizador lee la forma anidada y avisa (`the operations were nested inside 'contract'`); la petición ya no llama `contract` a la referencia de operaciones y el prompt exige la raíz |
| 2 | un modelo que no produce nada se registraba como `NO_CHANGES` | `parse_proposal` reescribía `PROPOSED` sin operaciones como `NO_CHANGES` | se elimina la reescritura: sin operaciones y sin explicación es `INTERPRETATION_INCOMPLETE`; `NO_CHANGES` exige justificación o declinaciones verificables |
| 3 | una propuesta con `status: NO_CHANGES` y operaciones perdía las operaciones (K009 del exp. 14) | el servicio cortaba antes de validar | las operaciones se validan; el estado contradictorio se registra como aviso |
| 4 | `ALREADY_SATISFIED` sobre una relación se rechazaba por no traer `target` | la verificación exigía identificador canónico | se verifica por el enunciado (extremos + predicado + polaridad) y por nombre + tipo en `ADD_ENTITY` |
| 5 | `ALREADY_SATISFIED` fallaba con `expected: {"retracted": false}` | comparación estricta contra `None` | `_claim_matches`: `false` ≡ `None` para «no retirado»; los estados se comparan sin distinguir mayúsculas |
| 6 | una entidad compilada en el exp. 13 no tenía `origin` y el parche lo dejaba vacío | el aplicador sólo fijaba el origen de la instrucción | con evidencia propia se deriva `DOCUMENT_EVIDENCE` de la evidencia que la entidad ya tenía |
| 7 | el modelo encadenaba dos parches sobre la misma entidad y el segundo esperaba el resultado del primero | KÜYEN valida cada operación contra la versión de base | mensaje explícito en el rechazo + el prompt pide una operación por objeto (limitación documentada) |

Los puntos 1–5 son defectos de KÜYEN, no del modelo: el modelo **sí** había interpretado la

## 3. Código y contratos modificados

| archivo | cambio |
| --- | --- |
| `src/kuyen/editing/operations.py` | lectura de propuestas anidadas (`_unwrap_envelope`) con aviso; sin reescritura silenciosa a `NO_CHANGES`; aviso cuando el estado contradice las operaciones |
| `src/kuyen/editing/outcome.py` (nuevo) | vocabulario cerrado de resultados (`COMMITTED`, `ALREADY_SATISFIED`, `NOT_APPLICABLE`, `REQUIRES_DATA_ACCESS`, `NEEDS_CLARIFICATION`, `OUT_OF_SCOPE`, `BLOCKED_BY_PERMISSION`, `INVALID_PROPOSAL`, `EXECUTION_FAILED`, `NO_CHANGES`, `NOT_EVALUATED`) y proyección por operación |
| `src/kuyen/editing/service.py` | `INTERPRETATION_INCOMPLETE`; `NO_CHANGES` justificado; propuesta contradictoria validada; `EditRun.outcome` |
| `src/kuyen/editing/validator.py` | `UPDATE_ENTITY` sin fusión (`ENTITY_NAME_COLLISION`); `UPDATE_ATTRIBUTE` declarado y tipado (`ATTRIBUTE_NOT_DECLARED`, `ATTRIBUTE_TYPE_MISMATCH`), con `ADD_FIELD` en la misma Antü; duplicación de relaciones por enunciado y conflicto de dirección; declinaciones verificables sin identificador |
| `src/kuyen/editing/applier.py` | `UPDATE_ENTITY` conserva origen, evidencia e historial (`previous_origin`, `changed`); `UPDATE_ATTRIBUTE` registra valor anterior, valor nuevo y origen; `_amend_in_place(keep_origin=…)`; origen documental derivado cuando el registro no lo tenía |
| `src/kuyen/editing/prompt.py` | guía y ejemplos de `UPDATE_ENTITY`, `UPDATE_ATTRIBUTE`, `UPDATE_RELATION`; instrucción de varias operaciones; espacio de la respuesta; una operación por objeto |
| `src/kuyen/api/memory.py` | `AntuEditResult.outcome` y `outcomes`; sólo `COMMITTED` tras el commit; `INTERPRETATION_INCOMPLETE` con su código en el ledger |
| `docs/GRAPH_EDIT_ANTU.md` · `.en.md` | estados del resultado (incluye `INTERPRETATION_INCOMPLETE`), `outcome`/`outcomes` y qué distingue entidad, atributo, relación y esquema |
| `CHANGELOG.md` | entrada del experimento 15 |

El contrato `kuyen-graph-edit-v2` no cambia de forma: cambian las comprobaciones y la forma de
leer la respuesta. `v1` sigue aceptándose.

## 4. Pruebas deterministas

`tests/editing/test_026_operational_coverage.py` (35 pruebas) cubre lo que el experimento 14 no
podía demostrar:

* `ADD_RELATION` dirigida, con identidad canónica de KÜYEN, sin evidencia y con versión nueva;
* relación ya existente declarada `ALREADY_SATISFIED` (sin versión) y relación duplicada
  propuesta como `APPLICABLE` (rechazo `DUPLICATE_OBJECT`);
* relación invertida (`RELATION_DIRECTION_CONFLICT`), extremo inexistente (`TARGET_NOT_FOUND`) y
  relación reflexiva (`SELF_RELATION`);
* `UPDATE_RELATION` como parche en sitio que conserva identidad, extremos, evidencia y
  `source_label`;
* `UPDATE_ENTITY`: renombrado que conserva identidad, relaciones, atributos y evidencia, con
  `previous_origin` y nombre anterior en la revisión; colisión de nombre (`ENTITY_NAME_COLLISION`);
  nombre vacío; `expected` ausente; instrucción ambigua;
* `UPDATE_ATTRIBUTE`: atributo declarado y fijado sin tocar el resto de la ficha; atributo no
  declarado; tipo inválido; `expected` obligatorio; corrección de un valor existente con el
  anterior conservado; `ADD_FIELD` + `UPDATE_ATTRIBUTE` con `depends_on` en una sola Antü;
* instrucción larga con tres operaciones confirmadas; instrucción larga con una parte ambigua y
  dos confirmadas (resultados mixtos);
* `NO_CHANGES` justificado, `NO_CHANGES` sin explicación (`INTERPRETATION_INCOMPLETE`),
  `NO_CHANGES` contradictorio con operaciones, respuesta ilegible, `OUT_OF_SCOPE` uniforme,
  declinaciones mixtas, `dry_run` (`NOT_EVALUATED`), repetición (`REPLAYED` → `ALREADY_SATISFIED`);
* atomicidad: una operación rechazada no escribe nada y no marca la aceptada como confirmada;
* normalización: operaciones anidadas en `contract` y en `proposal`, precedencia de la raíz;
* declinaciones verificables sin identificador y origen documental derivado.

```
python3 -m pytest -q tests/                                            # 527 passed, 3 skipped
python3 -m pytest -q tests/editing/test_026_operational_coverage.py     # 35 passed
```

Referencia: la línea base del experimento 14 era 495 pruebas (492 PASS + 3 opt-in SKIPPED). Se
mantiene: **530 pruebas, 527 PASS, 3 SKIPPED**.

instrucción. El punto 7 es una limitación del contrato actual, no un fallo oculto.

## 5. Inferencias reales

Mismo proveedor (`https://api.deepseek.com/v1`), mismo modelo (`deepseek-flash`), mismos
parámetros que el experimento 13 (`temperature=0`, `max_tokens=8192`, `json_mode`), sin fallback y
sin reintentos automáticos. Las dos primeras filas se ejecutaron **antes** de la corrección del
normalizador y se conservan en `evidence/pre_fix_raw_responses.json`; el resto, después.

| ANTÜ | caso | estado | outcome | propuestas | aplicadas | declinadas | rechazadas | versión | s | USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| K004-DRY-SHORT | long_vs_short_short | VALIDATED | NOT_EVALUATED | 1 | 1 | 0 | 0 | VER-8732e4ef6f56 | 4.35 | 0.007161 |
| K004-DRY-LONG | long_vs_short_long | REJECTED | INVALID_PROPOSAL | 3 | 0 | 0 | 1 | VER-8732e4ef6f56 | 8.75 | 0.008604 |
| K004-REL | relation_addition | COMMITTED | COMMITTED | 1 | 1 | 0 | 0 | VER-5baf121c2f66 | 3.41 | 0.006815 |
| K004-ENT | entity_rename | COMMITTED | COMMITTED | 1 | 1 | 0 | 0 | VER-883de544771d | 4.26 | 0.007268 |
| K004-ATTR-DECL | attribute_declared_and_set | COMMITTED | COMMITTED | 2 | 2 | 0 | 0 | VER-b178df431e88 | 3.97 | 0.0075 |
| K004-ATTR | attribute_correction | COMMITTED | COMMITTED | 1 | 1 | 0 | 0 | VER-05288440f2d2 | 2.73 | 0.007143 |
| K004-SAT | already_satisfied | REJECTED | INVALID_PROPOSAL | 1 | 0 | 0 | 1 | VER-05288440f2d2 | 4.31 | 0.007678 |
| K004-CLAR | ambiguous_target | CLARIFICATION_REQUIRED | NEEDS_CLARIFICATION | 1 | 0 | 0 | 0 | VER-05288440f2d2 | 4.68 | 0.00754 |
| K004-SAT2 | already_satisfied_after_fix | NO_CHANGES | ALREADY_SATISFIED | 1 | 0 | 1 | 0 | VER-05288440f2d2 | 8.18 | 0.00851 |
| K004-LONG2 | long_instruction_after_fix | REJECTED | INVALID_PROPOSAL | 3 | 0 | 1 | 1 | VER-05288440f2d2 | 12.23 | 0.010125 |
| K004-LONG3 | long_instruction_after_claim_fix | REJECTED | INVALID_PROPOSAL | 3 | 0 | 0 | 2 | VER-05288440f2d2 | 9.54 | 0.009124 |
| K005-LONG | long_multi_operation | COMMITTED | COMMITTED | 3 | 3 | 0 | 0 | VER-23dfee10a0ae | 7.01 | 0.008952 |

Detalle por caso (petición literal, propuesta, validadores y preservación) en
`evidence/real_runs.json`; resumen tabular en `benchmarks/runs.csv`.

### 5.1 Incorporación de relación (KUYEN-004, `K004-REL`)

Petición: «El Instituto para la Diversificación y Ahorro de la Energía es un organismo adscrito
al Ministerio para la Transición Ecológica y el Reto Demográfico: incorpora esa relación de
pertenencia entre ambas entidades.»

El modelo propuso una única `ADD_RELATION` con los dos extremos existentes, predicado `part_of`,
etiqueta «forma parte de», polaridad `POSITIVE` y modalidad `FACT`, citando la instrucción.
KÜYEN comprobó existencia e identidad de ambos extremos, ausencia de duplicado, ausencia de la
dirección contraria y el permiso `DATA_WRITE`, y confirmó `VER-5baf121c2f66`:

* la relación queda con `status: INSTRUCTED`, `evidence_ids: []`, `sources: []` y origen
  `ANTU_INSTRUCTION` (no se fabricó evidencia documental);
* relaciones 14 → 15, entidades 15, nada perdido (`preservation.lost = []`);
* la versión de base `VER-8732e4ef6f56` sigue sin esa relación.


### 5.2 Actualización de entidad (KUYEN-004, `K004-ENT`)

Petición: corregir la denominación de la central a «Central Hidráulica Reversible Los Guájares»
conservando la forma anterior como alias. El modelo propuso una `UPDATE_ENTITY` con
`expected.name` y `value.name` + `value.aliases`. Resultado en `VER-883de544771d`:

| propiedad | antes | después |
| --- | --- | --- |
| `entity_id` | `ent_7e7f581782f7f38e5d7e` | `ent_7e7f581782f7f38e5d7e` (sin cambios) |
| `name` | Central Hidráulica Reversible Los Guajares | Central Hidráulica Reversible Los Guájares |
| `aliases` | `["Los Guajares"]` | `["Los Guajares", "Central Hidráulica Reversible Los Guajares"]` |
| relaciones que la tocan | 4 | 4 |
| `evidence_ids` | evidencia documental | la misma evidencia documental |
| `amended` / `instruction_edits` | — | `true` / cambio `["name","aliases"]` con el valor anterior |

No se creó ninguna entidad, no se fusionó ninguna otra y la versión anterior sigue mostrando el
nombre antiguo (`previous_versions_still_readable` en `evidence/acceptance.json`). La revisión
guarda además `previous_origin`, de modo que la procedencia anterior es reconstruible.

### 5.3 Actualización de atributo (KUYEN-004, `K004-ATTR-DECL` y `K004-ATTR`)

Primera petición: declarar `estado_operativo` (texto) en el tipo `product` y fijarlo en
«operativa» para la central. El modelo propuso **dos** operaciones (`ADD_FIELD` y
`UPDATE_ATTRIBUTE`) y ambas se aplicaron en `VER-b178df431e88` (esquema versionado + atributo).

Segunda petición: corregir el valor a «en mantenimiento». `VER-05288440f2d2` registra la
revisión `previous: "operativa"`, `current: "en mantenimiento"`, y **no** crea ninguna afirmación
(`assertions` 11 antes y después): un atributo no es un hecho documentado.

### 5.4 Instrucción larga con varias operaciones (KUYEN-005, `K005-LONG`)

Una sola instrucción de ocho frases con tres cambios sobre objetos distintos. El modelo propuso
tres operaciones y KÜYEN confirmó las tres en `VER-23dfee10a0ae`:

1. `ADD_FIELD` `rol` (texto) en `person`;
2. `UPDATE_ATTRIBUTE` `rol = "investigador del CSIC"` en Óscar Monroig;
3. `ADD_RELATION` «Óscar Monroig participa en AQUALICIOUS» (`participates_in`, sin evidencia).

Nada perdido, versión anterior intacta y `verify()` correcto.

### 5.5 Comparación breve / larga sobre la misma base

Las dos peticiones se evaluaron con `dry_run` sobre la misma versión de origen
(`VER-8732e4ef6f56`), de modo que la única diferencia es la formulación:

| métrica | breve (`K004-DRY-SHORT`) | larga (`K004-DRY-LONG`) |
| --- | --- | --- |
| caracteres | 189 | 780 |
| operaciones propuestas | 1 | 3 |
| operaciones válidas | 1 | 2 |
| objetivo correcto | sí | sí |
| tiempo | 4.35 s | 8.75 s |
| tokens entrada / salida | 20 941 / 732 | 21 251 / 1 857 |
| resultado | `VALIDATED` | `REJECTED` (el tercer parche encadenado no se puede validar) |

La longitud no impide la interpretación: la versión larga produce **más** operaciones y las dos
primeras son válidas. Lo que hace fracasar la larga no es la longitud sino que el modelo dividió
un cambio en dos parches encadenados sobre la misma entidad (§8, limitación 1).

### 5.6 Instrucción ya satisfecha e instrucción ambigua

* `K004-SAT2`: «Confirma que el IDAE financia la Central…». El modelo declaró `ALREADY_SATISFIED`
  y nombró la relación existente; KÜYEN lo verificó por el enunciado y registró
  `NO_CHANGES` / `ALREADY_SATISFIED` sin crear versión. En `K004-SAT`, antes de la corrección, la
  misma respuesta se rechazaba porque la comprobación exigía un `target`.
* `K004-CLAR`: «Corrige la denominación de la estación». El modelo pidió aclaración con las dos
  candidatas; KÜYEN registró `CLARIFICATION_REQUIRED` / `NEEDS_CLARIFICATION` sin versión.

### 5.7 Operaciones anidadas: la evidencia del defecto

`evidence/pre_fix_raw_responses.json` conserva la respuesta literal del modelo antes de la
corrección:

```json
{"status":"PROPOSED","contract":{"schema_version":"kuyen-graph-edit-v2",
 "operations":[{"operation_id":"op-1","op":"ADD_RELATION", "…": "…"}]}}
```

KÜYEN leyó **cero** operaciones de esa respuesta (`proposal.operations == []`) y el experimento 14
lo habría registrado como `NO_CHANGES`. Con el normalizador corregido, la misma petición produce
tres operaciones y dos válidas (`K004-DRY-LONG`), y la instrucción larga de KUYEN-005 se confirma
con sus tres cambios.


## 6. Versiones

| KÜYEN | versiones antes | versiones ahora | vigente ahora | `verify()` |
| --- | --- | --- | --- | --- |
| KUYEN-001 | 2 | 2 | VER-6d440968cbb3 | True |
| KUYEN-002 | 2 | 2 | VER-36bafc9dcf2f | True |
| KUYEN-003 | 3 | 3 | VER-b54579461c44 | True |
| KUYEN-004 | 1 | 5 | VER-05288440f2d2 | True |
| KUYEN-005 | 4 | 5 | VER-23dfee10a0ae | True |
| KUYEN-006 | 2 | 2 | VER-71b8665042d5 | True |
| KUYEN-007 | 1 | 1 | VER-34b7b1f4eecb | True |
| KUYEN-008 | 5 | 5 | VER-529b4688b446 | True |
| KUYEN-009 | 1 | 1 | VER-884d87f21f7a | True |
| KUYEN-010 | 2 | 2 | VER-aa3c7866061c | True |

23 versiones al empezar, 28 al cerrar. Las ocho memorias sin instrucciones nuevas conservan
exactamente sus versiones; las dos que cambiaron sólo crecieron, conservando cada versión
anterior legible y verificable. Comprobado en `evidence/state_before.json`,
`evidence/state_after.json` y `evidence/acceptance.json` (`ten_memories_verify`,
`eight_memories_untouched`, `versions_only_grew_where_authorised`,
`previous_versions_still_readable`).

## 7. Comparación con los experimentos 13 y 14

Los méritos se separan: lo que aporta el modelo y lo que aportan los controles de KÜYEN.

| métrica | 13 | 14 | 15 |
| --- | --- | --- | --- |
| evaluaciones reales | 25 | 23 | 14 |
| confirmadas | 5 | 8 | 6 |
| ya satisfechas (`ALREADY_SATISFIED`) | 0 | 0 | 1 |
| sin cambios (`NO_CHANGES`) | 16 | 11 | 1 |
| rechazadas | 3 | 2 | 4 |
| aclaración | 1 | 1 | 1 |
| fallos de ejecución | 0 | 1 | 2 (sólo antes de la corrección) |
| `UPDATE_ENTITY` | no probado | no probado | **confirmado** |
| `UPDATE_ATTRIBUTE` | no probado | no probado | **confirmado (2 versiones)** |
| `ADD_RELATION` con LLM real | no | no | **confirmado** |
| operaciones por instrucción larga | 0 | 0–1 | **3 confirmadas** |
| propiedades perdidas en objetos modificados | 7 | 0 | **0** |
| coste USD | 0.229773 | 0.190396 | 0.112531 |

1. **Comprensión de la instrucción.** El modelo entendía las instrucciones en 13 y 14 más de lo
   que KÜYEN registraba: la respuesta anidada en `contract` lo demuestra. Ese avance **no** es
   mérito del modelo en 15: es una corrección determinista del normalizador.
2. **Exactitud de las operaciones propuestas.** En 15 el modelo propone la operación correcta en
   9 de 12 ejecuciones y propone de más (un parche encadenado o una declinación sin objetivo) en
   3. El mérito aquí sí es del modelo; el prompt ampliado con `UPDATE_ENTITY`,
   `UPDATE_ATTRIBUTE` y `UPDATE_RELATION` hizo posibles dos operaciones que en 14 nunca aparecían.
3. **Exactitud de los objetivos.** Correcta en todas las ejecuciones confirmadas, incluida la
   instrucción ambigua, que se detuvo en vez de adivinar.
4. **Correctitud de la ejecución.** Mérito de KÜYEN: 6 confirmadas y ninguna aplicación parcial.
   Las 4 rechazadas no escribieron nada.
5. **Conservación de propiedades no modificadas.** `preservation.lost = []` en las 12
   ejecuciones; `error` en 0. En 15 aparecen por primera vez objetos *entidad* y *atributo*
   modificados sin pérdida (identidad, relaciones, evidencia, otros atributos).
6. **Integridad de las nuevas versiones.** 28/28 verifican y las anteriores siguen siendo legibles.

## 8. Limitaciones

1. **Dos parches encadenados sobre el mismo objeto en una Antü.** El modelo dividió «cambiar el
   nombre y añadir un alias» en dos `UPDATE_ENTITY` y el segundo esperaba el resultado del
   primero. KÜYEN valida cada operación contra la versión de base, así que rechaza la Antü
   completa (`EXPECTED_VALUE_MISMATCH`, con un mensaje que lo explica). Es una limitación del
   contrato, no silenciada: el prompt pide ahora una operación por objeto y un `expected` tomado
   de la versión.
2. **Declinaciones que exigen un objetivo que el modelo no envía.** En `K004-LONG3` el modelo
   declaró `ALREADY_SATISFIED` para un `UPDATE_ENTITY` sin `target`; KÜYEN no puede verificar la
   afirmación y la rechaza. Es el comportamiento correcto (fail closed), pero limita al modelo.
3. **Instrucción larga sobre estado ya cambiado.** `K004-LONG2`/`K004-LONG3` reutilizan el texto
   escrito para el estado anterior a `K004-ENT`; el modelo respondió «ya está satisfecho» en dos
   de las tres partes y KÜYEN no pudo verificarlo en su totalidad. Se documenta como evidencia,
   no se reintenta en bucle.
4. **`expected` en declinaciones.** `_verify_already_satisfied` compara sólo las claves
   declaradas; una clave omitida no se comprueba. Es la misma semántica que `_check_expected`.
5. **`recorded_at` de las revisiones en el grafo es `null`.** Se mantiene a propósito: la
   identidad de una versión no puede depender del reloj (prueba
   `test_the_version_identity_does_not_depend_on_token_metering`); el instante exacto vive en el
   ledger y en el commit.
6. **KUYEN-005 no tenía un atributo de negocio declarado**; el atributo `rol` se declara en la
   misma ejecución. El atributo existente que sí se corrigió en dos versiones es el de KUYEN-004.


## 9. Coste verificado

Los tokens son los que devuelve el proveedor en cada respuesta (`usage`), no una estimación; el
importe aplica la tarifa documentada en el experimento 13 para `deepseek-flash` (entrada como
*cache miss*, hora punta: 0.30 USD/Mtok de entrada y 1.20 USD/Mtok de salida).

| tanda | ejecuciones | tokens entrada | tokens salida | USD |
| --- | --- | --- | --- | --- |
| antes de la corrección | 2 | 41 978 | 2 931 | 0.016111 |
| después de la corrección | 12 | 266 595 | 13 701 | 0.096420 |
| **total** | **14** | **308 573** | **16 632** | **0.112531** |

El *metering* no entra en ningún hash canónico ni en la procedencia de la versión.

## 10. Criterios de aceptación

`evidence/acceptance.json` comprueba 24 criterios contra las memorias reales (no contra
fixtures) y todos pasan:

| criterio | resultado |
| --- | --- |
| relación incorporada, con origen `ANTU_INSTRUCTION` y sin evidencia inventada | ok |
| relación ausente de la versión de base | ok |
| entidad renombrada en sitio, misma identidad, mismas relaciones | ok |
| revisión con el valor anterior y el origen anterior | ok |
| soporte documental conservado (`evidence_ids`, `amended`, `instruction_edits`) | ok |
| atributo declarado en el esquema y valor confirmado, sin afirmaciones nuevas | ok |
| valor anterior del atributo registrado | ok |
| instrucción larga con tres operaciones confirmadas en otra memoria | ok |
| el modelo sí había producido operaciones antes de la corrección; KÜYEN las descartaba | ok |
| la misma petición produce operaciones válidas después de la corrección | ok |
| los resultados distinguen al menos cuatro estados operativos | ok |
| ninguna limitación registrada como `NO_CHANGES` | ok |
| las diez memorias verifican; ocho intactas; sólo dos crecieron | ok |
| versiones anteriores legibles | ok |

```
python3 experiments/KUYEN_ANTU_OPERATIONAL_COVERAGE_15/scripts/snapshot.py after
python3 experiments/KUYEN_ANTU_OPERATIONAL_COVERAGE_15/scripts/analyze.py    # 24/24
```

## 11. Reproducibilidad

```bash
# pruebas deterministas (sin créditos)
python3 -m pytest -q tests/                                              # 527 passed, 3 skipped
python3 -m pytest -q tests/editing/test_026_operational_coverage.py      # 35 passed

# estado de las diez memorias y de los artefactos preservados
python3 experiments/KUYEN_ANTU_OPERATIONAL_COVERAGE_15/scripts/snapshot.py before
python3 experiments/KUYEN_ANTU_OPERATIONAL_COVERAGE_15/scripts/snapshot.py after

# inferencias reales (requiere DEEPSEEK_API_KEY; no ejecuta OpenViking)
set -a && . ./.env && set +a
python3 experiments/KUYEN_ANTU_OPERATIONAL_COVERAGE_15/scripts/run_real.py

# verificación de los criterios de aceptación y del manifiesto
python3 experiments/KUYEN_ANTU_OPERATIONAL_COVERAGE_15/scripts/analyze.py
python3 experiments/KUYEN_ANTU_OPERATIONAL_COVERAGE_15/scripts/manifest.py
```

`scripts/run_real.py` omite las ejecuciones ya registradas: repetirlo no vuelve a gastar créditos
ni duplica versiones.

## 12. Manifiesto

`MANIFEST.json` contiene el SHA-256 de cada archivo de este experimento, el estado Git inicial y
final y el resumen de la suite. Se genera justo antes de su propio commit, así que
`git.head_at_manifest` es el último commit de documentación anterior a él y el que lo contiene
aparece en `git log` (no puede contenerse a sí mismo). Los artefactos de los experimentos 13 y 14
no se modificaron: sus 703 archivos tienen el mismo hash antes y después
(`evidence/state_before.json` y `evidence/state_after.json`, clave `preserved`).

