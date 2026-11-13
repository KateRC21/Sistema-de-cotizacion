# Asistente de compras

Comparación de alimentos, aseo y hogar entre **Jumbo** y **Superboom**, con referencia en Medellín. El grafo interpreta la solicitud, consulta las dos tiendas en paralelo y entrega tres presupuestos con un informe. La normalización convierte unidades en Python y el modelo solo clasifica equivalencias entre identificadores reales. El presupuesto cuenta presentaciones enteras; no lo calcula el modelo.

Las cotizaciones salen del catálogo público de cada tienda. Son precios del sitio web en la fecha de consulta, con `estado_verificacion = consulta_publica`. No quedan confirmados como precio de góndola ni incluyen domicilio: si el envío no viene en la fuente, el total confirmado sigue vacío.

## Tiendas

Revisión del 13 de noviembre de 2026:

| Tienda | Decisión |
| --- | --- |
| Jumbo | Se consulta `https://www.jumbocolombia.com/api/catalog_system/pub/products/search`. Su robots.txt no prohíbe `/api/`. |
| Superboom | Se consulta `https://web.superboom.net/shop?search=`. Cubre el Valle de Aburrá y su robots.txt no prohíbe rutas. El precio se lee del marcado schema.org. |
| Éxito | Descartado. `robots.txt` prohíbe `/api/` y `/s?`. |
| Carulla | Descartado. `robots.txt` prohíbe `/api/` y `/s?`. |
| Euro | Descartado. `robots.txt` prohíbe `/busca/` y cualquier URL con `?`. |
| La Vaquita | Descartado para búsqueda. `robots.txt` prohíbe `/catalogsearch/`. |
| D1 | El catálogo VTEX respondió, pero el proyecto usa Superboom porque reparte en Medellín y el área metropolitana. |

El cliente HTTP se identifica con un User-Agent del proyecto y espera dos segundos entre peticiones al mismo dominio. No usa Playwright ni otro perfil de navegador.

## Grafo

`interpretar → validar → aclarar` (vuelve a interpretar) o, si el producto ya trae cantidad y unidad, `jumbo` y `superboom` en paralelo → `consolidar → normalizar → comparar → presupuesto → informe`.

Si no dicen la ciudad, se anota la suposición Medellín. Si no dicen tienda, se consultan las dos. Una tienda que no está disponible también queda anotada y se consultan Jumbo y Superboom. La cantidad y la unidad no se inventan: el nodo `aclarar` pausa con `interrupt()` y el grafo se reanuda con la respuesta. Después de tres aclaraciones sin esos datos, `cerrar` pasa al informe incompleto y no llama a las tiendas. Si una tienda falla, las ofertas de la otra se conservan.

Cada informe completo trae tres escenarios: todo en Jumbo, todo en Superboom y la combinación. Por producto se elige primero un equivalente; un sustituto más barato no lo desplaza. La cantidad se cubre con presentaciones enteras. El domicilio no viene en estas fuentes: el escenario lo declara con monto vacío y el total confirmado queda vacío. La recomendación prefiere quien cubre más productos y, a igual cobertura, el menor total parcial.

El diagrama queda en `docs/grafo.mmd` al ejecutar `--mermaid`.

## Pantalla

```bash
uv run streamlit run app.py
```

Se abre un formulario. La consulta a OpenAI y a las tiendas empieza al pulsar **Consultar**. Si falta la cantidad o la unidad, escribes la respuesta y **Revisar con el modelo** muestra la corrección entendida. La consulta sigue solo si pulsas **Sí, es correcto**. Mientras no confirmes, ese intento no se gasta.

## Entorno

Hace falta [uv](https://docs.astral.sh/uv/) y Python 3.12.

```bash
uv sync
copy .env.example .env
uv run python main.py
uv run python main.py --mermaid
uv run streamlit run app.py
uv run python main.py --interpretar "2 kg de arroz Diana y 1 litro de leche en Jumbo, en Medellín"
uv run pytest
uv run pytest tests/test_presupuesto.py
uv run pytest tests/test_grafo.py
uv run pytest -m red -o addopts=
uv run pytest -m llm -o addopts=
```

`uv run pytest` no llama a las tiendas ni a OpenAI. Incluye las rutas del grafo, los tres presupuestos y el informe. `-m red` busca «arroz» en Jumbo y Superboom. `-m llm` interpreta una solicitud y clasifica una equivalencia con la clave de `.env`.

También se puede consultar desde Python:

```bash
uv run python -c "from tools.jumbo import consultar_jumbo; r = consultar_jumbo('arroz'); print(r.ofertas[0].nombre, r.ofertas[0].precio, r.ofertas[0].url_fuente)"
uv run python -c "from tools.superboom import consultar_superboom; r = consultar_superboom('arroz'); print(r.ofertas[0].nombre, r.ofertas[0].precio, r.ofertas[0].url_fuente)"
```
