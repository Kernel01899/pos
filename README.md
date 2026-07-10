# Negocito POS — Prototipo

Punto de venta ligero para micronegocios en Puerto Rico. Resuelve lo que
ATH Móvil Business, Clover y Square **no** hacen bien para negocios pequeños:
inventario, cálculo automático de IVU, y reportes simples — construido para
integrarse con el pago que el cliente ya usa (ATH Móvil), no para competir
con él.

## Qué incluye este prototipo

- **Vender**: catálogo táctil, carrito, cálculo automático de IVU (11.5%),
  checkout con 3 métodos de pago (ATH Móvil simulado, tarjeta, efectivo).
- **Inventario**: agregar/editar/eliminar productos, alertas de stock bajo.
- **Reportes**: ventas por período (hoy / 7 días / 30 días), desglose por
  método de pago, productos más vendidos, inventario bajo.

## Nota sobre "ATH Móvil"

El botón de pago con ATH Móvil genera una **referencia simulada**
(`ATH-SIM-XXXXXXXX`). No hay integración real con la API de ATH Business —
eso requeriría credenciales de comerciante reales. En una versión de
producción, ese punto del código (`create_sale` en `app.py`, sección
"Simulación de cobro ATH Móvil") se reemplazaría por una llamada real a su
API para generar el cobro (pATH) y confirmar el pago vía webhook.

## Cómo correrlo

### Opción A — directo con Python (para probar rápido)

```bash
cd negocito-pos
pip install -r requirements.txt
python app.py
```

Abre `http://localhost:5055` en el navegador. Ya trae 4 productos de
ejemplo cargados para que puedas probar el flujo de inmediato.

### Opción B — Docker (recomendado para tu servidor)

```bash
cd negocito-pos
docker compose up -d --build
```

Esto construye la imagen, corre la app con `gunicorn` (no el servidor de
desarrollo de Flask) y guarda `negocito.db` en un volumen de Docker
(`negocito_data`) para que los datos sobrevivan a un `docker compose down`
o a un rebuild. Abre `http://TU_SERVIDOR:5055`.

Comandos útiles:

```bash
docker compose logs -f        # ver logs en vivo
docker compose down           # detener (los datos persisten en el volumen)
docker compose up -d --build  # reconstruir tras cambios en el código
```

Si prefieres Docker sin compose:

```bash
docker build -t negocito-pos .
docker run -d -p 5055:5055 -v negocito_data:/app/data --name negocito-pos negocito-pos
```

**Antes de exponerlo a internet real**: pon esto detrás de un reverse proxy
con HTTPS (Nginx, Caddy o Traefik) y considera agregar autenticación básica,
ya que ahora mismo cualquiera que llegue a la URL puede vender y editar
inventario.

## Stack

- Backend: Flask + SQLite (archivo `negocito.db`; en Docker vive en el
  volumen `/app/data`, configurable con la variable `DB_DIR`)
- Servidor de producción: gunicorn (2 workers)
- Frontend: HTML/CSS/JS vanilla, sin build step, mobile-first
- Sin dependencias externas de pago (todo corre localmente)

## Siguientes pasos sugeridos

1. Integración real con la API de ATH Business (o Stripe/Square como
   respaldo para tarjeta).
2. Autenticación multi-negocio (hoy es de un solo negocio).
3. Exportar reportes a PDF/CSV para el CPA del negocio.
4. Modo offline (service worker) para zonas con mala conexión o durante
   apagones — relevante dado el contexto energético de la isla.
