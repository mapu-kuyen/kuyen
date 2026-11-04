# KUYEN_OPENVIKING_VLM_CONFIGURATION_05

**Objeto:** configuración pública, segura y verificada del proveedor OpenAI para el VLM de la
instancia OpenViking administrada por KÜYEN.
**Workspace:** `/tmp/kuyen_hardening_01/kuyen` — HEAD `5fd8777a8305097792380fceb9ff861de208147a`
(*Release KÜYEN 0.2.0*, detached; `main` en el mismo commit). `VERSION` `0.2.1rc1` (intacto).
**Fecha:** 2026-11-02. **OpenViking efectivo:** **0.5.0** (`openviking-sdk` 0.1.15, `~/.venvs/openviking`).

```
VEREDICTO: OPENVIKING_VLM_CONFIGURATION_PASS
```

La configuración está implementada, es pública, es segura, está verificada contra el cargador
real de OpenViking 0.5.0 (incluido el mecanismo oficial de interpolación `os.path.expandvars`)
y el **smoke test real se ejecutó**: OpenViking recibió el documento, invocó al proveedor
configurado (`openai` / `gpt-4o-mini` / `https://api.openai.com/v1`) y persistió L0 y L1 en
español que parafrasean el documento. KÜYEN no hizo ninguna llamada de inferencia.

Tres corridas mínimas (una ingesta = una inferencia cada una) porque el arnés tuvo **dos
defectos propios**, ambos documentados en `smoke_test_history.json`; ninguna repetición ocultó
un fallo del proveedor. La clave nunca apareció en logs, artefactos ni salidas.


---

## 1. Identidad y preservación

| dato | valor |
|---|---|
| HEAD | `5fd8777a8305097792380fceb9ff861de208147a` — sin cambios |
| Entradas de estado al inicio / al final | **56 / 61** (las 5 nuevas son de este experimento) |
| `git reset` / `checkout` / `clean` / rebase | **ninguno ejecutado** |
| Workspace reconstruido desde `5fd8777` | **no** |
| `pyproject.toml` | intacto (`7cef38e9…61bf0`) |
| `VERSION` | intacto (`9f286730…b376b3`) |
| Hardening 01–05, Quickstart 02, Source Unit 03 | presentes y sin tocar |
| `KuyenAuthority`, commit canónico, 18 campos, procedencia, `source_unit()`, formatos persistidos | **no modificados** |
| README general, CI, metadatos de publicación, Quickstart | **no modificados** |

### 1.1 Los cuatro archivos incompletos de E2E_01

Inspeccionados y **preservados con hash idéntico**; no se promovieron ni se usaron en la ruta
nueva:

| archivo | hash (inicio = fin) |
|---|---|
| `src/kuyen/extraction/config.py` | `b735c68b45ad9e3b…4a4a7` |
| `src/kuyen/extraction/openai_provider.py` | `b477b1a8a083a655…df22c1` |
| `src/kuyen/extraction/schema.py` | `cb3817b462675064…4e2c07` |
| `src/kuyen/errors.py` | `ecdda5457802cd73…8e581` |

Ninguno se importa desde `kuyen.vlm`, `kuyen.projection.openviking` ni desde la API pública.

### 1.2 Cambios de este experimento

| archivo | tipo | contenido |
|---|---|---|
| `src/kuyen/vlm.py` | **nuevo** | `VlmProviderConfig`, `OpenVikingVlmRuntime`, `VlmConfigurationError` (310 líneas) |
| `src/kuyen/projection/openviking.py` | modificado | `start_isolated_server(..., vlm=, server_overrides=)`, escritura `0600`, entorno hijo propio, `_write_private_config` |
| `src/kuyen/__init__.py` | modificado | exporta los tres símbolos nuevos |
| `tests/unit/test_vlm_configuration.py` | **nuevo** | 23 pruebas offline |
| `tests/unit/test_015_extraction.py` | modificado | 3 llamadas ahora declaran `model=` explícito (reparación de la suite rota por los cambios incompletos de E2E_01; **no** restaura ningún modelo por defecto) |

Patch reproducible (5 archivos, 844 líneas, `6e9f262b…5c3b`, aplica limpio sobre un árbol
prístino de `5fd8777` con `patch -p1 --dry-run`).

---

## 2. API pública implementada

```python
from kuyen import VlmProviderConfig, OpenVikingVlmRuntime, VlmConfigurationError
```

| símbolo | firma |
|---|---|
| `VlmProviderConfig` | `(model, provider="openai", api_base="https://api.openai.com/v1", api_key_env="OPENAI_API_KEY", timeout_s=60.0, max_retries=0, temperature=None, api_key=None)` |
| `OpenVikingVlmRuntime` | `(root, config, server_bin=None, port=None, health_timeout=150.0)` → `start() · restart(config=None) · stop() · status()` |
| `VlmConfigurationError` | `code = "VLM_CONFIGURATION_INVALID"` |

Detalle completo en `public_api.md` y `public_api.json`.

Decisiones de contrato:

* **`model` es obligatorio**: no hay valor por defecto y `gpt-6-luna` no aparece en el código
  nuevo (comprobado por prueba);
* **la credencial puede recibirse directamente** (`api_key=...`) o resolverse del entorno
  (`api_key_env=`, por defecto `OPENAI_API_KEY`);
* **`provider` sólo admite `openai`**; un endpoint OpenAI-compatible local se rechaza con
  `VLM_CONFIGURATION_INVALID` (extensión futura, no implementada);
* `repr()`, `str()`, `to_public_dict()` y `status()` **nunca** contienen la credencial;
* no se exporta ningún símbolo de extracción y `OpenAIExtractionProvider` sigue fuera de la API.

---

## 3. Configuración real de OpenViking (verificada, no asumida)

Versión inspeccionada: **0.5.0**. Evidencia en `openviking_schema_verification.json`,
`openviking_version.json` y `vlm_provider_evidence.json`.

| hecho | cómo se verificó | resultado |
|---|---|---|
| La sección es `vlm` de `ov.conf` y su esquema es `VLMConfig` | lectura de `openviking_cli/utils/config/vlm_config.py` y `open_viking_config.py:212` | `provider`, `model`, `api_key`, `api_base`, `temperature`, `max_retries` (def. 3), `timeout`, `backend`, `max_tokens`, `credentials[]` |
| OpenViking expande `${VAR}` | lectura de `config_loader.py::load_json_config` → `os.path.expandvars(raw)` (línea 88) | confirmado |
| La expansión usa el entorno del **proceso servidor** | ejecución: el `ov.conf` de KÜYEN se parseó con el cargador real teniendo `KUYEN_VLM_API_KEY` en el entorno | `api_key_expanded_from_child_env: true` |
| Con la variable ausente la referencia **no** se resuelve | ejecución: mismo fichero, variable eliminada | `api_key` = literal `${KUYEN_VLM_API_KEY}` → KÜYEN **debe** fallar antes de arrancar (y lo hace) |
| El bloque escrito es aceptado por el cargador real | `OpenVikingConfigSingleton.initialize(config_path=…)` | `parsed_by_openviking: true`, `provider=openai`, `model`, `api_base`, `timeout=45.0`, `max_retries=0` |
| `OPENVIKING_VLM_API_KEY` no sirve como atajo | `grep -rn` en el paquete instalado | existe en `consts.py` y **no se lee en ninguna parte** → no se usa |
| Campos desconocidos en `vlm` | ejecución con un campo inventado | **sólo aviso** (`Ignoring unknown config field 'vlm.…'`), no error → el bloque es mínimo por construcción (7 campos, todos reales) |

Bloque generado (referencia, nunca el secreto) — `ov_conf.sanitized.json`:

```json
"vlm": {
  "provider": "openai",
  "model": "<modelo configurado por el usuario>",
  "api_base": "https://api.openai.com/v1",
  "api_key": "${KUYEN_VLM_API_KEY}",
  "timeout": 60.0,
  "max_retries": 0
}
```

---

## 4. Seguridad del secreto

| requisito | implementación | prueba |
|---|---|---|
| No en texto plano en `ov.conf` | sólo `${KUYEN_VLM_API_KEY}` | `test_ov_conf_serialization_contains_a_reference_and_no_secret` |
| No en logs, excepciones ni manifests | el valor nunca se interpola en mensajes; el error nombra la variable | `test_missing_api_key_names_the_variable_and_never_leaks`, `test_secret_is_absent_from_every_artifact` |
| No en el repositorio | no se escribe en ningún fichero versionado | barrido de artefactos |
| No en objetos serializados | `to_public_dict()`, `status()`, `handle["vlm"]` | `test_secret_is_absent_from_every_artifact` |
| No en `repr()` | `__repr__`/`__str__` propios en ambas clases | idem |
| No en cabeceras de autenticación de OpenViking | la clave VLM no se usa como `api_key` del cliente; `KUYEN_OPENVIKING_API_KEY` es otra | `test_openai_key_and_openviking_server_key_are_different_secrets` |
| Entorno específico del subproceso | `env = dict(os.environ)` + `env[KUYEN_VLM_API_KEY] = secret` | `test_environment_reference_is_used_and_os_environ_is_untouched`, `test_secret_reaches_only_the_child_environment` |
| Reinicio controlado al cambiar modelo o credencial | `restart()` compara `sha256(vlm_block + fingerprint(secreto))` | `test_start_is_idempotent_and_restart_follows_a_configuration_change` |

Además: `ov.conf` se escribe con `0600` de forma atómica (`tmp` + `os.replace`), y una variable
`KUYEN_VLM_API_KEY` heredada del llamador se **elimina** antes de fijar la propia, para que una
clave obsoleta del entorno no decida con qué se autentica la instancia.


---

## 5. Reutilización del ciclo de vida

No se creó un segundo administrador. `OpenVikingVlmRuntime.start()` llama a
`kuyen.projection.openviking.start_isolated_server()` y `stop()` a `stop_server()`; la clase sólo
añade idempotencia, reinicio y vista pública. `start_isolated_server` se extendió de forma
compatible hacia atrás:

* `vlm=` → valida y **resuelve la credencial antes de escribir o lanzar** (fallo cerrado sin
  estado parcial);
* `server_overrides=` → permite registrar `with_bot`/`bot_api_url` sin inventar URLs;
* escritura `0600` atómica; `child_env_keys` (sólo nombres) en el handle; cierre del descriptor
  del log en el padre tras `Popen`.

Comportamiento probado: salud (`/health` con `healthy: true`), fallo temprano si el binario no
existe (sin escribir `ov.conf`), fallo si el proceso muere al arrancar, y parada ordenada con
`port_still_open: false`. Nunca se lee ni se escribe la configuración global del usuario y nunca
se detiene un servidor que KÜYEN no arrancó.

---

## 6. Pruebas offline (23 pruebas, `tests/unit/test_vlm_configuration.py`)

| # del encargo | prueba(s) |
|---|---|
| 1 configuración válida | `test_valid_configuration_renders_the_openviking_block`, `test_openai_is_the_default_provider_and_api_base` |
| 2 configuración incompleta | `test_incomplete_configuration_is_rejected` (8 parametrizaciones) |
| 3 ausencia de API key | `test_missing_api_key_names_the_variable_and_never_leaks`, `test_api_key_can_come_from_the_environment` |
| 4 modelo no declarado | `test_model_must_be_declared_explicitly` |
| 5 serialización de `ov.conf` | `test_ov_conf_serialization_contains_a_reference_and_no_secret` |
| 6 referencia a variable de entorno | `test_environment_reference_is_used_and_os_environ_is_untouched` |
| 7 propagación al proceso hijo | `test_secret_reaches_only_the_child_environment` |
| 8 ausencia en archivos y logs | `test_secret_is_absent_from_every_artifact` |
| 9 reinicio al modificar configuración | `test_start_is_idempotent_and_restart_follows_a_configuration_change` |
| 10 fallo de arranque y limpieza | `test_missing_binary_fails_before_writing_anything`, `test_missing_credential_fails_before_spawning`, `test_server_that_exits_early_is_reported` |
| 11 separación de credenciales | `test_openai_key_and_openviking_server_key_are_different_secrets` |
| 12 sin extracción directa desde KÜYEN | `test_no_direct_extraction_is_reachable_from_the_vlm_configuration` (sin imports de proveedor; ningún módulo nuevo `kuyen.extraction*`/`openai`; sólo sockets a `127.0.0.1`) |

Resultado: **23 passed** (`logs/10_offline_tests.log`). Ninguna prueba abre conexiones externas.

---

## 7. Smoke test real: EJECUTADO (PASS)

`experiments/.../smoke_vlm.py` (lanzado con `run_smoke.sh`) arranca una instancia aislada de
OpenViking con el `ov.conf` de KÜYEN, ingesta un Markdown pequeño, espera el registro L0
persistido y lee L0/L1 por la API documentada (`GET /api/v1/content/abstract|overview`).

### 7.1 Resultado de la corrida válida (`smoke_test.json`, run 3)

| dato | valor |
|---|---|
| `status` | **`LIVE_VLM_SMOKE_PASS`** |
| intentos | **1** (una ingesta, una inferencia) |
| modelo | `gpt-4o-mini` (configurado explícitamente por el operador) |
| proveedor / endpoint | `openai` / `https://api.openai.com/v1` |
| `task_id` | `a6de079a-ca9d-4463-b33e-6066fb7c54fd` (`status: success`) |
| tiempo hasta L0 | **12 s**, 3 sondeos |
| L0 (abstract) | 158 caracteres — «El directorio "acta-vlm-smoke" contiene documentación relacionada con el seguimiento de un proyecto de iluminación solar en la comuna ficticia de Bahía Clara.» |
| L1 (overview) | 2 163 caracteres con navegación y descripción detallada (menciona «12 de las 18 luminarias») |
| `credential_in_log` | **false** |
| parada | `terminated: true`, `port_still_open: false`, `pid_alive: false` |

Evidencia durable en `evidence/`: `run3_l0.abstract.md`, `run3_l1.overview.md`, `run3_ov.conf`.
Los ficheros L0/L1 llevan `generated_by: {component: SemanticProcessor, trigger: resource_ingest}`,
lo que acredita que los produjo OpenViking, no KÜYEN.

### 7.2 Cronología de las tres corridas (transparencia)

| run | resultado registrado | qué ocurrió de verdad | defecto del arnés |
|---|---|---|---|
| 1 | `LIVE_VLM_SMOKE_FAILED` | **la inferencia funcionó**: L0 y L1 persistidos | `wait_processed(timeout=600)` → `ReadTimeout`: en 0.5.0 la tarea queda en `processing_queue` cuando falta el backend de embeddings local, aunque la generación semántica ya ocurrió |
| 2 | `LIVE_VLM_SMOKE_PASS` → **corregido a `INVALID_PASS`** | no confirmada | el predicado de disponibilidad aceptó el marcador `[Directory abstract is not ready]` (1 sondeo, 0,0 s) |
| 3 | **`LIVE_VLM_SMOKE_PASS`** | confirmada por el arnés | — |

Detalle y correcciones en `smoke_test_history.json`. Se hicieron **3 llamadas** de inferencia en
total; cada repetición está motivada por un defecto del arnés, no por un fallo del proveedor.

### 7.3 Selección del modelo

`KUYEN_VLM_MODEL` no venía declarado. Para no inventar un identificador se consultó
`GET /v1/models` con la credencial del operador (metadatos, **sin tokens facturables**, 136
modelos visibles) y se eligió `gpt-4o-mini`: el modelo chat compatible más barato disponible, sin
particularidades de `reasoning`. El contrato de KÜYEN no fija ningún modelo; para otro modelo
basta `export KUYEN_VLM_MODEL=<modelo>` y repetir `run_smoke.sh`.

### 7.4 Cómo reproducirlo

```bash
export OPENAI_API_KEY=...        # nunca se imprime ni se escribe en el repositorio
export KUYEN_VLM_MODEL=<modelo>  # modelo explícito del usuario
sh experiments/KUYEN_OPENVIKING_VLM_CONFIGURATION_05/run_smoke.sh
```

Sin `OPENAI_API_KEY` el runner sale con código 2 y el mensaje `LIVE_VLM_SMOKE_BLOCKED`, sin
ninguna conexión; y **no** usa `DEEPSEEK_API_KEY` (proveedor distinto, fuera de alcance).


---

## 8. Compile Runtime: diagnóstico (no corregido)

Detalle en `compile_runtime_analysis.md` y `compile_runtime_diagnosis.json`. Resumen para 0.5.0:

| configuración | qué es | defecto |
|---|---|---|
| `vlm.*` | proveedor de inferencia para L0/L1 | sin configurar en 0.5.0 |
| `compile_api.base_url` | **Compile task API externa**; vacía ⇒ `compile` responde 503 (`openviking/service/compile_service.py:316`) | `""` |
| `server.with_bot` / `server.bot_api_url` | proxy a **VikingBot** (gateway de chat), no el compilador | `False` / `http://localhost:18790` |

VikingBot está presente (`~/.venvs/openviking/bin/vikingbot`, `vikingbot gateway`) pero **no** es
el motor de compilación: habilitar `with_bot` no resuelve el 503. `vlm.api_base` no se reutiliza
como `compile_api.base_url`. Queda para el experimento siguiente identificar el runtime de
Compile y su protocolo exacto en esta versión.

---

## 9. Regresión y distribución

| comprobación | resultado |
|---|---|
| Suite completa (`PYTHONPATH=src pytest -q`) | **388 tests · 386 passed · 0 failed · 0 errors · 2 skipped** (referencia 365/363/2; +23 nuevas) |
| Pruebas nuevas | 23/23 passed |
| Quickstart (desde wheel y sdist, fuera del repo) | **4/4 PASS** — wheel 3.11, wheel 3.13, sdist 3.11, sdist 3.13 |
| `pip check` (venv limpio con la wheel instalada) | `No broken requirements found.` |
| Importación de la wheel instalada | `kuyen.vlm` presente; los 3 símbolos nuevos importables; `kuyen.__all__` = 28 |
| Core sin SDK de proveedor | `importlib.util.find_spec("openai")` → `None`; el paquete instala sin extras |
| `pyproject.toml`, `VERSION`, CI, metadatos | sin cambios |

Ninguna regresión: los tres fallos que aparecieron al inicio de la suite eran consecuencia de los
cambios incompletos de E2E_01 (`OpenAIExtractionConfig` sin `model`), reparados en `test_015` con
tres llamadas explícitas a `model=`; **no** se restauró ningún modelo por defecto.

---

## 10. Hallazgos y limitaciones

1. **`storage.vectordb.project` es un campo desconocido en 0.5.0** (aviso
   `Ignoring unknown config field`). Es preexistente en la configuración de KÜYEN y **no se tocó**
   en este experimento: no afecta al VLM, pero conviene limpiarlo cuando se revise `storage`.
2. **`OPENVIKING_VLM_API_KEY` no se usa** en 0.5.0 pese a existir en `consts.py`; por eso la
   entrega de la credencial se hace por la referencia `${KUYEN_VLM_API_KEY}` del propio `ov.conf`
   (mecanismo verificado), y no por esa variable.
3. **Los campos desconocidos de `vlm` no se rechazan**, sólo se avisan: la protección es que el
   bloque es mínimo y generado por código, no por el usuario.
4. **El servidor real se arrancó** en las tres corridas del smoke test. Los ficheros L0/L1 los
   escribe `SemanticProcessor` con `trigger: resource_ingest`; se conservan en `evidence/`.
5. **Compile Runtime sigue sin resolverse** (503 por `compile_api.base_url` vacío): es competencia
   del experimento siguiente, como indica el encargo.
6. Los cuatro archivos incompletos de E2E_01 **siguen incompletos**; este experimento no los
   promovió ni los usó.
7. `test_015_extraction.py` se modificó sólo para que la suite refleje la eliminación del modelo
   implícito; es un cambio de pruebas, no de comportamiento.
8. **La cola de ingesta queda en `processing_queue`** en 0.5.0 cuando falta el backend de
   embeddings local (`llama-cpp-python`): el `add_resource(wait=True)` y el `wait_processed` no
   retornan aunque la generación semántica ya haya ocurrido. El arnés, por eso, espera el registro
   L0 persistido. Para el experimento siguiente conviene decidir si se configura
   `embedding.dense.provider` (p. ej. remoto con la misma credencial) — **no se hizo aquí** por
   quedar fuera del alcance VLM.
9. **Dos defectos propios del arnés** quedaron documentados con su corrección: el bloqueo en
   `wait_processed` (run 1) y un predicado de disponibilidad que aceptaba el marcador
   `[Directory abstract is not ready]` (run 2, reclasificado como `INVALID_PASS`). Nada de eso se
   ocultó en el informe.
10. **`KUYEN_VLM_MODEL` no venía declarado**: el modelo se eligió a partir de `/v1/models`
    (`gpt-4o-mini`), con justificación y posibilidad de override. KÜYEN no fija ningún modelo.

---

## 11. Veredicto

```
OPENVIKING_VLM_CONFIGURATION_PASS
```

| criterio de PASS | estado |
|---|---|
| 1. Configuración mediante API pública de KÜYEN | **demostrado** (`VlmProviderConfig`, `OpenVikingVlmRuntime`) |
| 2. API key recibida de forma segura | **demostrado** (parámetro o entorno; nunca en `ov.conf`, logs, `repr` ni objetos serializados; `credential_in_log: false`) |
| 3. Configuración correcta del VLM de OpenViking | **demostrado** contra el cargador real de 0.5.0, incluida la expansión de la referencia, **y** por la inferencia real |
| 4. Propagación al proceso correcto | **demostrado** (entorno del hijo; `os.environ` intacto; `child_env_keys: [KUYEN_VLM_API_KEY]`) |
| 5. Ausencia de llamadas directas paralelas desde KÜYEN | **demostrado** (sin imports de proveedor; sólo sockets a loopback; `kuyen.extraction` no se importa) |
| 6. Smoke test real a través de OpenViking | **demostrado** — `LIVE_VLM_SMOKE_PASS`, 1 ingesta, L0 158 y L1 2 163 caracteres generados por `SemanticProcessor` |
| 7. Regresión sin fallos nuevos | **demostrado** (388 tests, 0 fallos; 4/4 distribución; `pip check` limpio) |

Caveats declarados, no ocultos:

* la generación L0/L1 funciona, pero la **cola de tareas no avanza** (`processing_queue`) porque
  el backend de embeddings local (`llama-cpp-python`) no está instalado; la recuperación
  semántica/vectorial queda degradada y no se probó aquí;
* el `compile` sigue devolviendo 503 (`compile_api.base_url` vacío): **fuera de alcance**, para el
  experimento del Runtime de Compile;
* se hicieron 3 inferencias por dos defectos del arnés, documentados uno a uno.

No se publica nada y no se inicia la integración del Compile Runtime.


---

## 12. Entregables

Directorio `experiments/KUYEN_OPENVIKING_VLM_CONFIGURATION_05/`:

| archivo | contenido |
|---|---|
| `REPORT.md` | este informe (copia) |
| `public_api.md` / `public_api.json` | API pública implementada, firmas y garantías |
| `ov_conf.sanitized.json` | `ov.conf` generado, sin secretos |
| `child_environment.json` | entorno efectivo del proceso (sólo nombres y valores no secretos) |
| `openviking_version.json` | versión, orígenes de esquema y comandos de verificación |
| `openviking_schema_verification.json` | salida del cargador real de OpenViking sobre el `ov.conf` de KÜYEN |
| `vlm_provider_evidence.json` | qué se demostró sobre el proveedor VLM y qué no |
| `smoke_test.json` | resultado del smoke test (PASS, corrida 3) |
| `smoke_test.run1.json` / `smoke_test.run2.json` / `smoke_test_history.json` | las tres corridas, con el defecto de arnés de cada repetición |
| `evidence/` | L0/L1 persistidos por OpenViking (runs 1 y 3), `ov.conf` y extracto saneado del log |
| `compile_runtime_diagnosis.json` / `compile_runtime_analysis.md` | diagnóstico de Compile Runtime |
| `smoke_vlm.py` | ejecutor real del smoke test (una sola llamada, sin reintentos) |
| `verify_openviking_schema.py` | verificación reproducible contra el cargador instalado |
| `diagnose_compile_runtime.py` | diagnóstico reproducible de Compile Runtime |
| `git_state_initial.txt` / `git_state_final.txt` | HEAD, estado y diffstat |
| `hashes_initial.txt` / `hashes_final.txt` | SHA-256 de los archivos implicados |
| `logs/10_offline_tests.log`, `logs/20_suite.log`, `logs/20_suite.xml` | pruebas |
| `patch/vlm_configuration_05.patch` | patch reproducible (`6e9f262b…5c3b`, 5 archivos) |
| `MANIFEST.json` | SHA-256 de cada archivo del directorio |
