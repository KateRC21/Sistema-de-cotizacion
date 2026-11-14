# Asistente de compras

Compara alimentos, aseo y hogar entre **Jumbo** y **Superboom**, con referencia en Medellín. Recibe una solicitud en lenguaje natural, consulta las dos tiendas en paralelo, **recomienda una oferta por producto con foto y precio**, deja cambiarla, calcula tres presupuestos y arma un carrito con el subtotal por tienda y el enlace de cada producto.

Está construido con **LangGraph** (flujo, pausas con `interrupt()` y envíos en paralelo con `Send`), **LangChain** (`ChatPromptTemplate | ChatOpenAI` con salida estructurada) y **Pydantic**. El modelo interpreta el texto y clasifica equivalencias; las conversiones de unidades, los precios y los presupuestos los calcula Python con `Decimal`.

Las cotizaciones salen del catálogo público de cada tienda. Son precios del sitio web en la fecha de consulta, con `estado_verificacion = consulta_publica`. No quedan confirmados como precio de góndola ni incluyen domicilio: si el envío no viene en la fuente, el total confirmado sigue vacío y nunca se cuenta como cero.

## Qué hace

1. **Interpreta** la solicitud: producto, cantidad, unidad, marca, características, ciudad y tiendas.
2. **Consulta** Jumbo y Superboom, y conserva nombre, presentación, precio, moneda, tienda, URL, **foto**, fecha de consulta y disponibilidad.
3. **Normaliza** las unidades y compara por precio por unidad base.
4. **Clasifica** cada oferta como equivalente, sustituto o no comparable.
5. **Recomienda** una oferta por producto y deja escoger otra.
6. **Presupuesta** tres escenarios: todo en Jumbo, todo en Superboom y combinado.
7. **Arma el carrito** con subtotal por tienda y el enlace de cada producto.

### Unidades y conversiones

Se puede pedir en **kilos, libras, gramos, litros, mililitros, unidades, docenas** o por **paquete, bolsa, caja, botella, lata y frasco**.

| Unidad pedida | Conversión |
| --- | --- |
| 1 kg | 1000 g |
| 1 libra | 500 g (libra comercial colombiana) |
| 1 litro | 1000 ml |
| 1 docena | 12 unidades |
| paquete, bolsa, caja, botella, lata, frasco | 1 unidad (empaque) |

Si se pide por empaque («1 paquete de galletas»), se compara el precio de cada paquete sin importar su peso. Cuando el nombre de la oferta no trae peso ni volumen, la cantidad de piezas se lee del nombre («x30», «18 Unidades»).

### Recomendación y selección

- **Cantidad ausente:** el producto se busca como 1 empaque y queda anotado en «Suposiciones». Se puede cambiar en el carrito. Si no se entiende qué producto se quiere, el grafo pausa y pide aclaración.
- **Equivalentes:** si no se pide marca ni característica, la marca y la variedad común no importan. Otro tipo de producto (crema de leche, pan de leche, tostadas de arroz) queda como no comparable.
- **Oferta recomendada:** entre los equivalentes gana la que cubre lo pedido al **menor costo total** (precio por empaques enteros), no la de menor precio por kilo. Así 2 kg de arroz no se resuelven con un bulto de 10 kg. Sin equivalentes toma un sustituto; sin ninguno, la persona escoge.
- **Elegir otra:** en «Elige otras opciones» cada producto muestra hasta 8 ofertas con foto, de la más barata a la más cara. Al escoger una, **los presupuestos, la recomendación y el carrito se recalculan**. La oferta elegida manda en el presupuesto de su tienda y en el combinado.
- **Escenario recomendado:** gana el que cubre más productos y, si empatan, el de menor total.

## Tiendas

Revisión del 13 de noviembre de 2026:

| Tienda | Decisión |
| --- | --- |
| Jumbo | Se consulta `https://www.jumbocolombia.com/api/catalog_system/pub/products/search`. Su robots.txt no prohíbe `/api/`. Las búsquedas con varias palabras se codifican con `%20`; con `+` la API responde HTTP 400. |
| Superboom | Se consulta `https://web.superboom.net/shop?search=`. Cubre el Valle de Aburrá y su robots.txt no prohíbe rutas. El precio se lee del marcado schema.org. |
| Éxito | **No se consulta automáticamente.** Su `robots.txt` prohíbe `/api/` y `/s?`, y el sitio responde 403 con un desafío de Cloudflare. No se elude. La pantalla ofrece un enlace de búsqueda para que la persona abra en su navegador. |
| Carulla | Igual que Éxito: `robots.txt` prohíbe `/api/` y `/s?`. Solo enlace de búsqueda manual. |
| Euro | Descartado. `robots.txt` prohíbe `/busca/` y cualquier URL con `?`. |
| La Vaquita | Descartado para búsqueda. `robots.txt` prohíbe `/catalogsearch/`. |
| D1 | El catálogo VTEX respondió, pero el proyecto usa Superboom porque reparte en Medellín y el área metropolitana. |

El cliente HTTP se identifica con un User-Agent del proyecto y espera dos segundos entre peticiones al mismo dominio. No usa Playwright ni otro perfil de navegador. Si se quisiera agregar Éxito, la vía correcta es pedir autorización o importar un catálogo CSV identificado como dato de referencia.

## Grafo

`interpretar → validar → aclarar` (vuelve a interpretar) o, si el producto ya se puede buscar, `jumbo` y `superboom` en paralelo → `consolidar → normalizar → comparar → presupuesto → informe`.

- **Ciudad y tiendas:** si no se dicen, se anota la suposición (Medellín; Jumbo y Superboom).
- **Aclaración:** `aclarar` pausa con `interrupt()` y el grafo se reanuda con la respuesta. La pantalla activa la suposición de cantidad, así que solo pregunta cuando no entiende el producto. Con `suponer_cantidad=False` (el valor por defecto del grafo) también pregunta por cantidad y unidad. Tras tres rondas sin datos, `cerrar` pasa al informe incompleto sin llamar a las tiendas.
- **Fallos:** si una tienda falla, las ofertas de la otra se conservan.
- **Normalización:** el clasificador del modelo se llama **una vez por producto, en paralelo** (hasta 8 a la vez). Si falla la clasificación de un producto, solo ese queda sin clasificar. Las llamadas a OpenAI tienen límite de 60 s y 2 reintentos.

El diagrama queda en `docs/grafo.mmd` al ejecutar `--mermaid`.

## Presupuestos

Cada informe completo trae tres escenarios: todo en Jumbo, todo en Superboom y la combinación. Por producto se elige primero un equivalente; un sustituto más barato no lo desplaza. La cantidad se cubre con presentaciones enteras y se elige la oferta de **menor costo total**. El domicilio no viene en estas fuentes: el escenario lo declara con monto vacío y el total confirmado queda vacío. Los productos sin cotización y las condiciones no verificadas se listan en el informe junto con las fuentes.

## Pantalla

```bash
uv run streamlit run app.py
```

Orden de la pantalla:

1. **Instructivo** «¿Cómo pedir?» con las unidades y conversiones.
2. **Tu compra recomendada:** carrito con la oferta recomendada por producto.
3. **Comparación de presupuestos** y detalle por escenario.
4. **Suposiciones.**
5. **Elige otras opciones:** ofertas con foto para cambiar la recomendada. Bajo cada producto hay enlaces de búsqueda manual en Éxito y Carulla.
6. **Fuentes** y recorrido del grafo.

La consulta a OpenAI y a las tiendas empieza al pulsar **Consultar**. Con varios productos puede tardar cerca de un minuto, sobre todo por la pausa de dos segundos entre peticiones a cada tienda. Si no se entiende el producto, se escribe la respuesta y **Revisar con el modelo** muestra la corrección entendida; la consulta sigue solo si se pulsa **Sí, es correcto**.

## Estructura

| Ruta | Contenido |
| --- | --- |
| `app.py` | Pantalla Streamlit |
| `compras/grafo.py`, `routers.py` | Grafo de LangGraph y sus rutas |
| `compras/nodos/` | Interpretación, validación, consulta, normalización, comparación, presupuesto |
| `compras/carrito.py` | Opciones, recomendación, empaques, carrito y enlaces |
| `compras/presupuesto.py`, `informe.py` | Escenarios e informe |
| `compras/llm.py`, `prompts.py` | Cadenas de LangChain |
| `tools/` | Jumbo (VTEX), Superboom (HTML), cliente HTTP y conversiones |
| `tests/` | Pruebas |

## Entorno

Hace falta [uv](https://docs.astral.sh/uv/) y Python 3.12.

```bash
uv sync
cp .env.example .env          # en Windows: copy .env.example .env
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

`uv run pytest` no llama a las tiendas ni a OpenAI. Incluye las rutas del grafo, los presupuestos, el informe y el carrito (95 pruebas). `-m red` busca «arroz» en Jumbo y Superboom. `-m llm` interpreta una solicitud y clasifica una equivalencia con la clave de `.env`.

También se puede consultar desde Python:

```bash
uv run python -c "from tools.jumbo import consultar_jumbo; r = consultar_jumbo('arroz'); print(r.ofertas[0].nombre, r.ofertas[0].precio, r.ofertas[0].url_fuente)"
uv run python -c "from tools.superboom import consultar_superboom; r = consultar_superboom('arroz'); print(r.ofertas[0].nombre, r.ofertas[0].precio, r.ofertas[0].url_fuente)"
```
