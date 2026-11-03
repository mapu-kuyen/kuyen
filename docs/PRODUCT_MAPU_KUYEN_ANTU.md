# MAPU, KÜYEN y ANTÜ: qué es cada cosa

Documento de producto. Describe el comportamiento implementado en KÜYEN 0.2.1 y no atribuye
capacidades que solo se hayan simulado.

## MAPU — el documento

Un **MAPU** es el documento o contenido fuente: el texto que se incorpora, su identidad
(`mapu_id`), su versión, su `source_uri`, su hash y su procedencia (origen, fecha, licencia).
KÜYEN guarda el texto tal como se le entrega y lo direcciona por unidades de fuente
(`SOURCE_UNIT`), de modo que cada afirmación puede citarse con desplazamientos exactos.

El MAPU **no** se reescribe: si el documento original es una página HTML o un PDF, la
rendición textual que se ingesta es un artefacto declarado y hasheado, y el original se
conserva junto a ella. Un MAPU sin evidencia localizable no produce conocimiento admitido.

## KÜYEN — la memoria

Un **KÜYEN** es una memoria gráfica independiente: su propio almacén canónico, su propio
grafo (entidades, relaciones, afirmaciones, evidencia), su esquema, su ledger, sus versiones y
su historial de ANTÜ. Dos KÜYEN no comparten identificadores ni conocimiento, aunque sus MAPU
se parezcan: la misma instrucción puede aplicarse en uno y no en otro.

La memoria no es una aplicación: no ejecuta reglas de negocio ni guarda lógica operativa.

## ANTÜ — la instrucción

Un **ANTÜ** es una solicitud de modificación, corrección o evolución del conocimiento de un
KÜYEN, escrita en texto libre y portable. No es una lista de operaciones: el LLM la
interpreta con el contexto que ese KÜYEN le autoriza a ver y propone cero o más operaciones
(`ADD_ENTITY`, `UPDATE_ASSERTION`, `RETRACT_RELATION`, `ADD_FIELD`, …).

Cada operación se clasifica por separado: `APPLICABLE`, `ALREADY_SATISFIED`,
`NOT_APPLICABLE`, `REQUIRES_DATA_ACCESS`, `NEEDS_CLARIFICATION`, `OUT_OF_SCOPE` o
`BLOCKED_BY_PERMISSION`. KÜYEN conserva los resultados diferenciados y **no crea una versión
si ninguna operación cambia el grafo**.

## Quién hace qué

| actor | responsabilidad | no puede |
| --- | --- | --- |
| OpenViking 0.5.0 + Skill `knowledge-graph` | materializar el MAPU en artefactos nativos (entidades, relaciones, afirmaciones, evidencia) | decidir la admisión canónica |
| LLM de inferencia | interpretar el ANTÜ y proponer operaciones estructuradas | escribir en el grafo, validar permisos, inventar datos |
| KÜYEN (determinista) | validar estructura, identidad, valores, permisos, evidencia y procedencia; aplicar; versionar; verificar | confiar ciegamente en la propuesta del modelo |

## Permisos y límites

Cuatro permisos, evaluados por separado y aplicados dos veces (al construir el contexto y al
autorizar cada operación): `SCHEMA_READ`, `SCHEMA_WRITE`, `DATA_READ`, `DATA_WRITE`. Si un
ANTÜ solo puede ver el esquema, el contexto lo declara y las operaciones que necesitan datos
se rechazan o se marcan `BLOCKED_BY_PERMISSION`; los datos restringidos nunca se envían.

## Versionado y procedencia

`ANTÜ → LLM → OPERACIONES → VALIDACIÓN → EJECUCIÓN → VERIFICACIÓN → NUEVA VERSIÓN`.
Ambos caminos (documento y edición) terminan en el **mismo** commit canónico: mismo ledger,
mismo linaje, misma recuperación. La versión anterior se conserva y el cambio exacto queda
registrado (valores anteriores y nuevos, nodos afectados, motivos, operaciones rechazadas).

La procedencia distingue lo documental de lo instruido: `DOCUMENT_EVIDENCE` exige cita y
unidad de fuente; `ANTU_INSTRUCTION` registra la petición literal, su hash, la versión base y
el modelo, y **nunca** se presenta como verificado por el MAPU.

## Lo que este documento no afirma

KÜYEN no distribuye ANTÜ entre memorias, no coordina un grafo global y no convierte una
instrucción en una memoria nueva: cada KÜYEN decide localmente y versiona su propia historia.

## Actualizaciones parciales

Cuando un ANTÜ corrige un solo dato, KÜYEN cambia ese dato y nada más: la unidad, el contexto,
la modalidad, la polaridad, el ámbito y la atribución que el ANTÜ no nombró se conservan. La
afirmación anterior queda `SUPERSEDED` con su evidencia y la nueva registra el valor anterior.
Cambiar solo la modalidad o la atribución no crea otra afirmación: se anota en el historial de
la misma. Añadir un campo al esquema (`ADD_FIELD`) es estructura y se versiona igual que
cualquier otro cambio; no ejecuta validadores ni crea lógica de aplicación.
