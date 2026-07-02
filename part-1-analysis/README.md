# Parte 1 — Análisis del incidente

**Autor:** Gonzalo

**Fecha:** 12/11/2024

**Reporte inicial:** FinCore, 14:32 UTC

---

## TL;DR

A las **14:09:33 UTC**, el proveedor **Nexopay** empezó a devolver timeouts de 30s en todas las transacciones hacia el biller **CFE**. Desde ese momento hay 100% de fallo en ese rail, afectando a **más de un partner** (no solo FinCore).

**Severidad:** P1.
**Escalar a:** Vendor Ops / Provider Integrations (contacto técnico con Nexopay).

---

## 1. Cuándo empezó

**T0: 2024-11-12 14:09:33 UTC** — transacción `txn-011` (fincore / CFE / nexopay), primer `PROVIDER_TIMEOUT`.

Antes de esa hora, cero fallos en toda la ventana de 2 hs. El cambio es abrupto.

Query: `queries/01_timeline.sql`

---

## 2. Qué está fallando

Descomposición desde T0:

| provider | total | ok | fail |
|---|---|---|---|
| nexopay | 23 | 0 | 23 |
| openpay | 7 | 7 | 0 |

- **Biller afectado:** CFE (categoría electricity).
- **Proveedor afectado:** Nexopay.
- **Error:** `PROVIDER_TIMEOUT` — "Connection timed out after 30000ms".

Los 23 fallos comparten exactamente el mismo `error_code` y `error_message`. Sin dispersión → comportamiento sistemático, no ruido.

Queries: `queries/02_provider_biller.sql`, `queries/04_error_signature.sql`

---

## 3. Alcance: FinCore + otros partners

Cross-partner desde T0:

| partner_id | provider | total | fallidas | pct_fallo |
|---|---|---|---|---|
| fincore | nexopay | 20 | 20 | 100% |
| fincore | openpay | 7 | 0 | 0% |
| other_partner | nexopay | 3 | 3 | 100% |

Dos observaciones:

- `other_partner` también falla al 100% cuando usa Nexopay → el problema no es del partner, es de Nexopay.
- FinCore procesa OK por Openpay → su integración con Tapi está sana.

El fallo se da en todas las transacciones con el flujo Nexopay → CFE sin importar qué partner las envíe. FinCore reportó primero probablemente por volumen de transacciones.

Query: `queries/03_cross_partner.sql`

---

## 4. Evidencia del log

- **Latencia idéntica en todos los fallos:** 30001–30003 ms. El timeout parejo indica que el sistema está aplicando el corte al llegar al límite configurado, no una latencia variable del proveedor.
- **Sistema de retry funcionando:** 3 intentos por transacción, todos fallan con el mismo error → el reintento está ejecutándose como se espera, pero no cambia el resultado.
- **Openpay funcionando:** latencias normales (700–900 ms) durante toda la ventana. Descarta problemas de red o del servicio de pagos en general.

Con esto queda claro que Nexopay no está respondiendo dentro del tiempo esperado, y el problema está del lado del proveedor.

---

## Clasificación y escalamiento

**Severidad: P1**

- Servicio core (procesamiento de pagos) caído.
- Multi-partner impactado.
- Impacto directo en usuario final (no pueden pagar servicios).
- Revenue perdido para Tapi y partners.
- Reputacional: partner enterprise ya escaló.

**Equipo destino: Vendor Ops / Provider Integrations.**

No corresponde escalar a Producto/Ingeniería en primera instancia: el código de Tapi funciona correctamente (retry, logs, cutoff). El fallo está fuera del perímetro de Tapi.

---

## Acciones inmediatas (en paralelo al escalamiento)

- [ ] Verificar status page pública de Nexopay o canal de incidentes.
- [ ] Confirmar si ya hay un ticket técnico abierto con el proveedor.
- [ ] Identificar todos los partners que rutean CFE por Nexopay para comunicación proactiva.
- [ ] Evaluar viabilidad de rutear CFE temporalmente por Openpay como mitigación.

---

## Herramienta usada

Análisis hecho en **DBeaver Community Edition** sobre una base SQLite local cargada con `data/transactions.sql`.

Como bonus reproducible, incluyo `analysis.py` — script en Python que corre el pipeline completo (queries + parseo del log) en un solo comando.

## Cómo reproducir

### Opción 1 — DBeaver (recomendado)

1. Nueva conexión SQLite → apuntar a un archivo `.db` nuevo.
2. Abrir SQL Editor, pegar `data/transactions.sql`, ejecutar con `Alt + X`.
3. Correr las queries de `queries/` una por una con `Cmd + Enter`.

### Opción 2 — Python (para reproducir todo en un solo comando)

```bash
python3 analysis.py
```

Requiere solo Python 3.8+ (SQLite viene incluido).
