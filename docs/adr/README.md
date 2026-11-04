# Architecture Decision Records

Este directorio registra las decisiones arquitectónicas de KÜYEN.

## Convención

Antes de este realineamiento **no existía ningún ADR en el repositorio** (se comprobó: no hay
`adr/`, `ADR`, `DECISIONS.md` ni documentos numerados de decisión). Por eso se establece aquí la
convención y la numeración **empieza en `0001`**, sin posibilidad de conflicto con documentos
previos.

| Regla | Detalle |
|---|---|
| Nombre | `NNNN-titulo-en-kebab-case.md`, cuatro dígitos |
| Numeración | consecutiva; un número no se reutiliza ni se renumera |
| Estado | `Propuesto`, `Aceptado`, `Reemplazado por NNNN`, `Obsoleto` |
| Contenido mínimo | Contexto · Decisión · Motivo · Consecuencias · Decisiones no tomadas |
| Idioma | español, igual que los informes de `docs/reports/` y `docs/` |
| Inmutabilidad | un ADR aceptado no se reescribe: se corrige con uno nuevo que lo reemplace |

Los ADR no describen la implementación línea a línea; para eso están los informes de auditoría en
[`docs/architecture/audits/`](../architecture/audits/) y los informes de experimento en
`docs/`.

## Índice

| ADR | Título | Estado |
|---|---|---|
| [0001](0001-openviking-first-realignment.md) | Realineamiento arquitectónico: KÜYEN como autoridad canónica sobre OpenViking | Aceptado |
