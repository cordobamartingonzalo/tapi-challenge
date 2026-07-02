# Tapi — Global Support Analyst Challenge

Resolución del challenge técnico para la posición de **Global Support Analyst** en Tapi.

**Autor:** Martin Gonzalo Cordoba | **Fecha:** Julio 2026

---

## Mi enfoque

Encaré el challenge tratando de simular lo más fielmente posible lo que haría en el día 1 del rol: ante un reporte urgente de un partner enterprise, no quedarme con el síntoma que reporta el cliente, sino ir a la causa raíz con los datos y logs disponibles. Prioricé tres cosas:

1. **Análisis riguroso.** Cargué `transactions.sql` en DBeaver y armé queries progresivas — desde "¿cuándo empezó?" hasta "¿esto es transversal a más partners?" — para no saltar a conclusiones. El paso decisivo del caso es entender que el fallo no es del biller (CFE) ni del partner (FinCore), sino del proveedor upstream (Nexopay). Sin esa lectura, la comunicación al cliente y el escalamiento salen mal.
2. **Comunicación honesta al cliente.** El mensaje a FinCore está pensado para dar señal de control sin sobrecomprometerse — reconocer lo que estamos viendo del lado nuestro, no prometer un ETA que todavía no tenemos, y dar un compromiso concreto de próximo update.
3. **Automatización con criterio.** El flujo en n8n no es solo una alerta: incluye deduplicación (para no spamear el canal cada 5 min con el mismo incidente) y un enriquecimiento con Claude vía API que resume el impacto en un mensaje de Slack para que el equipo pueda revisarlo y tomar acción sobre el incidente.

Stack utilizado en todo el challenge: DBeaver + SQL + Python (sqlite3 in-memory) + n8n + Claude API + Slack Webhook

---

## Estructura del repo

```
tapi-challenge/
├── data/                          → Archivos originales del challenge
│   ├── transactions.sql
│   └── app.log
│
├── part-1-analysis/               → Análisis del incidente + queries + script
│   ├── README.md                  → Conclusiones detalladas + queries usadas
│   ├── analysis.py                → Script que reproduce todo el análisis
│   └── queries/
│       ├── 01_timeline.sql
│       ├── 02_provider_biller.sql
│       ├── 03_cross_partner.sql   
│       ├── 04_error_signature.sql
│       └── 05_t0_exact.sql
│
├── part-2-client-message/         → Mensaje de respuesta a FinCore (EN)
│   └── README.md
│
└── part-3-automation/             → Flujo de detección automática en n8n
    ├── README.md                  → Descripción del flujo + decisiones de diseño + futuras features
    ├── workflow-challenge.json              → Export del flujo (importable en n8n)
    └── diagram.png                → Screenshot del flujo armado
```

---

## Cómo reproducir el análisis (Parte 1)

Requiere Python 3.8+.

​```bash
git clone https://github.com/<usuario>/tapi-challenge.git
cd tapi-challenge/part-1-analysis
python3 analysis.py
​```

El script carga `transactions.sql` en una base SQLite, corre las 
queries y parsea `app.log`.

Como alternativa, se puede importar `data/transactions.sql` en DBeaver 
(o cualquier cliente SQL) y correr las queries de `part-1-analysis/queries/` 
manualmente. Es como armé el análisis originalmente.

---

## Índice de entregables

| Parte | Descripción | Link |
|-------|-------------|------|
| 1 | Análisis del incidente + queries SQL + clasificación de severidad | [`part-1-analysis/README.md`](./part-1-analysis/README.md) |
| 2 | Mensaje de respuesta a FinCore (en inglés) | [`part-2-client-message/README.md`](./part-2-client-message/README.md) |
| 3 | Flujo de detección automática en n8n | [`part-3-automation/README.md`](./part-3-automation/README.md) |

---

## Resumen ejecutivo del incidente

- **T0:** 12/11/2024 14:09:33 UTC
- **Causa raíz:** Proveedor Nexopay devuelve timeouts consistentes de 30s en todas las llamadas para el biller CFE.
- **Impacto:** 100% de fallo en transacciones ruteadas por Nexopay hacia CFE desde T0. **Cross-partner** — no solo FinCore.
- **Severidad:** P1.
- **Escalamiento:** Equipo con relación técnica con Nexopay
