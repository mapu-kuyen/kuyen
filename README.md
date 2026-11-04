# KÜYEN

**Memoria canónica, versionada y verificable para sistemas de conocimiento y agentes inteligentes.**

[English version](README.en.md) · [Documentación](#documentación) · [Instalación](#instalación) · [Inicio rápido](#inicio-rápido) · [Contribuir](CONTRIBUTING.md)

KÜYEN es una biblioteca Python para construir y mantener memorias estructuradas como grafos de conocimiento, con versiones inmutables, validación determinista y trazabilidad hasta las fuentes originales.

Permite que una aplicación o un agente incorpore conocimiento, consulte su evolución, proponga modificaciones y conserve evidencia verificable de cómo se construyó cada afirmación.

**KÜYEN separa la interpretación del conocimiento de su conservación.** Un modelo de lenguaje puede interpretar documentos o instrucciones; KÜYEN valida, gobierna y persiste los cambios aceptados.

## ¿Qué problema resuelve?

Los sistemas basados en documentos, modelos de lenguaje y agentes suelen tener dificultades para responder preguntas fundamentales:

- ¿De dónde proviene una afirmación?
- ¿Qué fragmento de un documento la respalda?
- ¿Qué cambió entre dos versiones del conocimiento?
- ¿Quién o qué proceso produjo una modificación?
- ¿Se puede recuperar una versión anterior?
- ¿Podemos comprobar que la memoria conserva su integridad?

KÜYEN aborda estos problemas mediante una memoria canónica cuyo contenido, procedencia y evolución pueden inspeccionarse y verificarse.

## ¿Qué es KÜYEN?

KÜYEN es una biblioteca de memoria gobernada. No es un agente ni un modelo de inteligencia artificial.

Sus componentes principales son:

- **Grafo canónico:** entidades, relaciones, afirmaciones y evidencias estructuradas.
- **MAPU:** registro del documento fuente y su contenido original.
- **SOURCE_UNIT:** fragmento identificable de un documento, utilizado para localizar y verificar evidencia.
- **Versiones inmutables:** cada cambio aceptado genera una nueva versión, sin reescribir las anteriores.
- **Trazabilidad:** permite recorrer una afirmación hasta su evidencia, fragmento y documento de origen.
- **Validación determinista:** las propuestas de modificación deben cumplir los contratos de integridad antes de ser persistidas.
- **Registro ANTÜ:** conserva las instrucciones y los resultados de sus ejecuciones.
- **Recuperación:** permite verificar, respaldar, restaurar y reconstruir memorias.

## ¿Cómo funciona?

KÜYEN admite dos caminos principales para evolucionar una memoria.

### 1. Incorporar conocimiento desde documentos

Un proceso externo interpreta o transforma documentos en una representación de grafo. KÜYEN recibe el documento canónico resultante, verifica sus contratos y conserva una nueva versión.

OpenViking puede participar como motor externo de procesamiento e incorporación mediante el adaptador correspondiente. No es un requisito para utilizar el núcleo de KÜYEN.

### 2. Modificar una memoria existente mediante ANTÜ

Una instrucción ANTÜ expresa un cambio que se desea realizar sobre el conocimiento existente.

Un modelo o componente externo puede interpretar la instrucción y proponer operaciones sobre el grafo. KÜYEN valida esas operaciones, comprueba las restricciones de integridad y persiste los cambios aceptados mediante una nueva versión.

La edición directa del grafo mediante ANTÜ no requiere volver a procesar el documento original con OpenViking.

En ambos caminos, KÜYEN conserva la procedencia y el historial de la evolución del conocimiento, y ambos terminan en el mismo protocolo de confirmación canónica.

## Características principales

| Capacidad | Qué ofrece |
|---|---|
| Memoria canónica | Representación estructurada de entidades, relaciones, afirmaciones y evidencias |
| Versionado | Historial inmutable y linaje de versiones |
| Procedencia | Relación verificable entre afirmaciones y fuentes |
| Validación | Escrituras sujetas a contratos deterministas |
| Integridad | Verificación de hashes, referencias y estructuras |
| ANTÜ | Registro, validación y aplicación controlada de instrucciones |
| Backup y restore | Respaldo y restauración verificables |
| Recuperación | Reconstrucción de versiones desde el almacenamiento canónico |
| Proyecciones | Integración opcional con motores externos |

## Qué KÜYEN no pretende hacer

Es importante delimitar sus responsabilidades:

- KÜYEN no es un LLM y no interpreta por sí solo el significado de un documento.
- No genera conocimiento autónomamente: recibe representaciones y propuestas producidas por procesos externos.
- No exige OpenViking, embeddings, proveedores de modelos ni conexión de red para operar su memoria canónica.
- No sustituye la evaluación de la calidad de las fuentes ni garantiza que una afirmación sea verdadera por el solo hecho de estar almacenada.
- No declara recuperación semántica nativa ni compilación nativa de OpenViking como capacidades del núcleo.
- No aporta un anclaje externo de confianza ni firmas: la verificación detecta una alteración que rompe los hashes, las referencias o la cadena del registro, pero no distingue una reescritura completa y consistente del almacén. Los límites exactos están en [SECURITY.md](SECURITY.md).

KÜYEN garantiza contratos de conservación y validación; la calidad de la interpretación depende del proceso que produce la información que se le entrega.

## Instalación

### Requisitos

- Python 3.10 o superior.
- Linux o macOS (sistemas POSIX).
- Sistema de archivos con soporte para las operaciones atómicas requeridas.
- Diseño de escritura única concurrente: un escritor por almacén.

Windows y los sistemas de archivos de red no están validados ni soportados en esta versión. Consulta [compatibilidad de plataformas](PLATFORM_COMPATIBILITY.md).

### Instalar desde GitHub

```bash
git clone https://github.com/mapu-kuyen/kuyen.git
cd kuyen

python -m venv .venv
source .venv/bin/activate

python -m pip install .
```

Para instalar el adaptador opcional de OpenViking:

```bash
python -m pip install ".[openviking]"
```

Para trabajar en desarrollo:

```bash
python -m pip install ".[dev]"
```

La instalación desde el repositorio es la vía soportada en la versión 0.3.0: todavía no hay
una distribución publicada en PyPI, por lo que `pip install kuyen` no está disponible.

## Inicio rápido

Crear una memoria KÜYEN:

```python
from kuyen import KuyenMemory

memory = KuyenMemory.create(
    "./memory",
    leftraru_id="LR-0001",
    purpose="Memoria de conocimiento"
)

print(memory.status())
```

El almacén queda asociado a la unidad responsable. La creación no inventa ni incorpora
conocimiento: establece el espacio canónico donde podrá persistirse, y `memory.current()`
todavía devuelve `None`.

Para incorporar un primer grafo aceptado:

```python
from kuyen import build_document

document = build_document(
    accepted_graph,
    {mapu_id: source_text},
    source_uris={mapu_id: source_uri},
)

result = memory.import_canonical(document)

print(result.version.version_id)
```

`accepted_graph`, `mapu_id`, `source_text` y `source_uri` representan los datos preparados por
el proceso de incorporación. Cada evidencia debe citar exactamente el `source_uri` de su MAPU:
si no se declara uno, `build_document` usa `viking://resources/<mapu_id>`, y una cita distinta
se rechaza al confirmar (`EVIDENCE_URI_MISMATCH`). Consulta el [Quickstart](QUICKSTART.md) para
ver el flujo completo y ejecutable.

### Consultar y verificar

```python
current = memory.current()
graph = memory.graph()
history = memory.history()

report = memory.verify()
assert report["ok"], report["problems"]
```

`verify()` no levanta excepciones: devuelve `ok` y la lista de `problems` para que un operador
vea exactamente qué está mal.

### Aplicar una instrucción ANTÜ

La ejecución y la persistencia son operaciones diferenciadas:

```python
execution = memory.execute_antu(
    antu,
    mapu_source="MAPU-02.txt"
)

if execution.status == "VALIDATED":
    result = memory.commit(execution)
```

`execute_antu` valida y prepara, y no escribe ninguna versión. `commit` solo persiste una
ejecución `VALIDATED`; una ejecución `REPLAYED` devuelve la versión ya confirmada y cualquier
otro estado (`REJECTED`, `NO_SEMANTIC_CHANGE`, `CONFLICT`) levanta `CommitError`. La validación
no equivale a una escritura automática.

Para la edición directa mediante un editor, consulta el contrato de `apply_antu` en
[PUBLIC_API.md](PUBLIC_API.md).

## Documentación

| Documento | Contenido |
|---|---|
| [QUICKSTART.md](QUICKSTART.md) | Recorrido práctico desde la instalación hasta la verificación |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Arquitectura, módulos y límites del sistema |
| [PUBLIC_API.md](PUBLIC_API.md) | API pública, operaciones y contratos |
| [DATA_MODEL.md](DATA_MODEL.md) | Modelo de entidades, relaciones, afirmaciones y evidencias |
| [VERSIONING.md](VERSIONING.md) | Dominios de versión e inmutabilidad |
| [ANTU_LIFECYCLE.md](ANTU_LIFECYCLE.md) | Ciclo de vida de las instrucciones ANTÜ |
| [CANONICAL_STORAGE.md](CANONICAL_STORAGE.md) | Almacenamiento canónico y protocolo de confirmación |
| [SIDECAR.md](SIDECAR.md) | Contrato de reconstrucción de versiones |
| [BACKUP_AND_RECOVERY.md](BACKUP_AND_RECOVERY.md) | Respaldo, restauración y recuperación |
| [ADAPTERS.md](ADAPTERS.md) | Proyecciones e integración con motores externos |
| [docs/GRAPH_EDIT_ANTU.md](docs/GRAPH_EDIT_ANTU.md) | Edición del grafo mediante ANTÜ |
| [docs/PRODUCT_MAPU_KUYEN_ANTU.md](docs/PRODUCT_MAPU_KUYEN_ANTU.md) | MAPU, KÜYEN y ANTÜ: qué es cada cosa |
| [SECURITY.md](SECURITY.md) | Modelo de seguridad y reporte de vulnerabilidades |
| [PLATFORM_COMPATIBILITY.md](PLATFORM_COMPATIBILITY.md) | Compatibilidad y limitaciones de plataforma |
| [CHANGELOG.md](CHANGELOG.md) | Cambios entre versiones |

La documentación de edición ANTÜ también está disponible en
[inglés](docs/GRAPH_EDIT_ANTU.en.md), y este README en [inglés](README.en.md).

## Pruebas

Desde el repositorio:

```bash
python -m pytest
```

La suite de producto se ejecuta sin requerir credenciales de proveedores externos ni servicios
de red. Las pruebas que necesitan una instancia real de OpenViking o un proveedor de modelos se
omiten salvo que se activen explícitamente (`KUYEN_RUN_OPENVIKING=1`, `KUYEN_RUN_REAL_MODEL=1`),
conforme a las instrucciones de sus respectivos experimentos o adaptadores.

## Estado del proyecto

**Versión del producto: 0.3.0**

KÜYEN cuenta con una distribución reconstruible desde un clon limpio, pruebas automatizadas y
una matriz de CI para Python 3.10, 3.11, 3.12 y 3.13.

El proyecto continúa evolucionando. Las capacidades de integración externa deben evaluarse según
sus contratos y pruebas específicas; no todas forman parte de las garantías del núcleo.

Consulta [CHANGELOG.md](CHANGELOG.md) para conocer los cambios entre versiones y
[PLATFORM_COMPATIBILITY.md](PLATFORM_COMPATIBILITY.md) para conocer las garantías y limitaciones
actuales.

## Contribuir

KÜYEN es un proyecto de software abierto. Las contribuciones, reportes de errores, propuestas y
revisiones son bienvenidos.

- [Guía para contribuir](CONTRIBUTING.md)
- [Reportar un problema](https://github.com/mapu-kuyen/kuyen/issues)
- [Política de seguridad](SECURITY.md)

Antes de proponer cambios, revisa los contratos públicos y las pruebas existentes. La
compatibilidad, la procedencia y la integridad de la memoria son propiedades centrales del
proyecto.

## Licencia

KÜYEN se distribuye bajo la licencia [Apache License 2.0](LICENSE). El texto completo e
inalterado está en [`LICENSE`](LICENSE) y el identificador SPDX `Apache-2.0` se declara en los
metadatos de la distribución.

La licencia cubre el software. No concede derechos sobre el nombre ni las marcas de KÜYEN, y no
se atribuye aquí un titular de derechos que el propietario del proyecto no haya declarado.

---

**KÜYEN — conocimiento estructurado, memoria verificable y evolución trazable.**

Repositorio: https://github.com/mapu-kuyen/kuyen
