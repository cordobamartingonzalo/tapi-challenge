# Parte 3 — Automatización en n8n

> _En construcción — pendiente de resolución._

Este entregable contendrá el flujo de n8n que detecta automáticamente incidentes del tipo del que atendemos en la Parte 1, antes de que el cliente los reporte.

**Requisitos del flujo:**
- Ejecución cada 5 minutos (cron).
- Consulta a la DB de transacciones para calcular tasa de error por biller/proveedor en los últimos 15 min.
- Umbral configurable (default 30%).
- Al superar el umbral, notificación a Slack con contexto útil: qué combinación proveedor+biller falla, desde cuándo, cuántas transacciones afectadas y qué partners impactados.

**Diseño que voy a considerar:**
- Deduplicación para no notificar el mismo incidente cada 5 minutos.
- Enriquecimiento con Claude vía API para generar un resumen en lenguaje natural del impacto.
- Umbral parametrizado como variable de entorno, no hardcodeado.

**Entregables:**
- `workflow.json` — flujo exportado desde n8n, importable.
- `diagram.png` — screenshot del flujo armado.
- Este README con descripción de nodos y decisiones de diseño.
