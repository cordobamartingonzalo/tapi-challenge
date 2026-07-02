# Parte 1 — Análisis del incidente

**Autor:** Martin Gonzalo Cordoba

**Reporte inicial:** FinCore, 14:32 UTC

---

## TL;DR

A las **14:09:33 UTC**, el proveedor **Nexopay** empezó a devolver timeouts de 30s en todas las transacciones hacia el biller **CFE**. Desde ese momento hay 100% de fallo en ese rail, afectando a **más de un partner** (no solo FinCore).

**Severidad:** P1.

**Escalar a:** equipo que gestiona la relación técnica con proveedores.

---

## 1. Cuándo empezó

Para ubicar el inicio del problema, agrupé las transacciones por minuto en `transactions.sql` y calculé el porcentaje de fallo en cada bucket. La curva muestra un cambio abrupto: hasta las 14:07 UTC no hay ni un solo fallo en toda la ventana de 2 hs, y a las 14:09:33 UTC aparece la primera transacción caída.

**T0 del incidente: 2024-11-12 14:09:33 UTC** — transacción `txn-011` (fincore / CFE / nexopay), primer `PROVIDER_TIMEOUT`.

Query utilizada: `queries/01_timeline.sql`

---

## 2. Qué está fallando

Con el T0 identificado, descompuse las transacciones desde ese momento por proveedor para ver dónde se concentraban los fallos.

| provider | total | ok | fail |
|---|---|---|---|
| nexopay | 23 | 0 | 23 |
| openpay | 7 | 7 | 0 |

Luego de analizar `transactions.sql` identifiqué 23 fallos que comparten exactamente el mismo `error_code` y `error_message`, sin dispersión — comportamiento sistemático, no ruido puntual.

- **Biller afectado:** CFE (categoría electricity).
- **Proveedor afectado:** Nexopay.
- **Error:** `PROVIDER_TIMEOUT` — "Connection timed out after 30000ms".

Queries utilizadas: `queries/02_provider_biller.sql`, `queries/04_error_signature.sql`

---

## 3. Alcance: FinCore + otros partners

El reporte inicial vino de FinCore, pero de manera protocolar revisé si otros partners estaban siendo afectados. Crucé partner con proveedor filtrando desde el T0.

| partner_id | provider | total | fallidas | pct_fallo |
|---|---|---|---|---|
| fincore | nexopay | 20 | 20 | 100% |
| fincore | openpay | 7 | 0 | 0% |
| other_partner | nexopay | 3 | 3 | 100% |

Aparecen dos datos importantes:

- `other_partner` también falla al 100% cuando usa Nexopay → el problema no es del partner, es de Nexopay.
- FinCore procesa OK por Openpay → su integración con Tapi está ok.

El fallo se da en todas las transacciones con el flujo Nexopay → CFE sin importar qué partner las envíe.

Query utilizada: `queries/03_cross_partner.sql`

---

## 4. Evidencia del log

Hasta acá el diagnóstico venía de la DB `transactions.sql`. Complementando con `app.log` pude confirmar tres cosas más que ayudan a cerrar la hipótesis:

- **Latencia idéntica en todos los fallos:** 30001–30003 ms. Un timeout alto y parejo indica que el sistema está aplicando el corte al llegar al límite configurado, no parece ser algo variable.
- **Sistema de retry funcionando:** 3 intentos por transacción, todos fallan con el mismo error → el reintento está ejecutándose como se espera, pero no cambia el resultado.
- **Openpay funcionando:** latencias normales (700–900 ms) durante toda la ventana. Descarta problemas de red o del servicio de pagos en general.

Con esto queda claro que Nexopay no está respondiendo dentro del tiempo esperado, y el problema está del lado del proveedor.

---

## Clasificación y escalamiento

Con el diagnóstico armado, propongo la siguiente clasificación:

**Severidad: P1**

- Servicio core (procesamiento de pagos) caído.
- Multi-partner impactado.
- Impacto directo en usuario final (no pueden pagar servicios).
- Revenue perdido para Tapi y partners.
- Reputacional: partner enterprise ya escaló.

**Equipo destino:** equipo que gestiona la relación técnica con proveedores.

---

## Acciones inmediatas (en paralelo al escalamiento)

- [ ] Verificar status page pública de Nexopay o canal de incidentes.
- [ ] Verificar internamente si ya existe un caso abierto con el proveedor por este tema.
- [ ] Identificar todos los partners que rutean CFE por Nexopay para comunicar de manera proactiva.

---

## Herramientas usadas

- **DBeaver** sobre una base SQLite local cargada con `data/transactions.sql`, para ejecutar las queries del análisis.
- **Python** (`analysis.py`) como bonus reproducible: corre el pipeline completo (queries + parseo del log) en un solo comando.

## Cómo reproducir

### Opción 1 — DBeaver

1. Nueva conexión SQLite → apuntar a un archivo `.db` nuevo.
2. Abrir SQL Editor, pegar `data/transactions.sql`, ejecutar con `Alt + X`.
3. Correr las queries de `queries/` una por una con `Cmd + Enter`.

### Opción 2 — Python (para reproducir todo en un solo comando)

```bash
python3 analysis.py
```
