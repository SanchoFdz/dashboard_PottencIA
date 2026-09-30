# Dashboard PottencIA / ODILO

Versión **interactiva y semanal** del deck mensual del comité
(`Presentaciones Datos/Datos PottencIA - <fecha>.pptx`). Reproduce las mismas
láminas y **los mismos números** que el notebook oficial `consumo_contenidos_3.ipynb`,
pero se actualiza solo con reemplazar los CSV que descargas del proveedor Odilo BI.

## Arrancar (local)

```bash
pip install -r requirements.txt      # solo la primera vez
streamlit run app.py
```

Se abre en el navegador (http://localhost:8501).

## Dos modos de datos

El pipeline detecta automáticamente la fuente:

- **Modo preparado (deployment):** si existe la carpeta `data/` con parquet slim,
  la app la usa. Es lo que se sube al repo y despliega en Streamlit Cloud (~2 MB, incluye
  `roster.parquet`, el denominador de licencias del embudo).
- **Modo CSV (desarrollo):** si NO existe `data/`, lee los CSV crudos del proveedor
  en el layout ODILO (`../mnt/data/current`, `../mnt/data/previous`,
  `../datos_analisis_estrategico_2026`).

## Deployment en Streamlit Community Cloud

1. `share.streamlit.io` → **New app** → repo `SanchoFdz/dashboard_PottencIA`, rama `main`,
   main file **`app.py`**.
2. Deploy. Streamlit instala `requirements.txt` y sirve la app con los parquet de `data/`.

### Actualización semanal (con deployment)

```bash
# 1. Coloca los CSV nuevos del proveedor en ../mnt/data/{current,previous}
#    (mueve el current viejo a previous). Snapshot mensual → ../datos_analisis_estrategico_2026
python preparar_datos.py        # regenera data/*.parquet (~1.3 MB)
git add data && git commit -m "datos <fecha>" && git push
# Streamlit Cloud redepliega solo.
```

En local sin deployment, basta reemplazar los CSV y pulsar **🔄 Recargar datos**
(no hace falta preparar parquet si borras/ignoras la carpeta `data/`).

## Actualización semanal (el flujo que pediste)

1. Descarga del portal **Odilo BI** los CSV del periodo (los 4 del mes:
   `Horas_de_aprendizaje_*.csv`, `Usuarios_mensuales_*.csv`, `Consumo_mensual_*.csv`,
   `consumo_por_usuario__*.csv`).
2. Mueve los CSV del `current` viejo a **`mnt/data/previous/`** y coloca los nuevos
   en **`mnt/data/current/`**.
3. (Solo al cerrar un mes) añade el snapshot mensual `consumo_por_usuario__<mes>.csv`
   a **`datos_analisis_estrategico_2026/`** para alimentar growth accounting, cohortes
   y la serie larga.
4. En el dashboard pulsa **Recargar datos**.

No hay que tocar código: el motor detecta automáticamente el archivo más reciente de
cada carpeta (`load_latest`, igual que el notebook).

## Secciones

Navegación y filtro viven en la barra superior (`st.segmented_control`), no en el sidebar:
**una fila de secciones** y debajo la fila de marca.

Depuración del 30-Sep-2026: de 16 secciones en tres grupos se pasó a **10 en una sola fila**,
en el orden del deck del comité. Salieron Resumen, Certificación, Centro y Nivel, Catálogo,
Formato, Ruta Máster, el bloque gateway y la comparación con el lift del deck. Sus funciones
siguen en `pipeline.py` (las usan `generar_taller_kpis.py` y `generar_onepager_ceo.py`).

**El filtro de marca solo aparece donde cambia los números.** Tendencias y Pulso se
calculan sobre la serie diaria de plataforma, que el proveedor no desglosa por universidad
(`SIN_MARCA` en `app.py`); ahí el control se oculta y el encabezado dice «global, sin
desglose por marca».

En **Panorama** el filtro sí está, y **cambia la fuente de los KPIs**:

| Filtro | Fuente | KPIs |
|--------|--------|------|
| `Todas` | serie diaria de plataforma | 4 (incluye usuarios efectivos) |
| una universidad | snapshot usuario×LE de esa marca | 3 (horas, contenidos, usuarios con consumo) |

Los dos juegos **no son comparables entre sí**: miden universos distintos (la serie diaria
reporta ~3x las horas del snapshot). Nunca se muestran en la misma fila.

Los bloques «Por marca» son comparaciones y **siempre muestran las cuatro universidades**,
con la seleccionada a opacidad plena y las demás atenuadas (`_opacidad()`).

La marca elegida se guarda en `st.session_state.marca_activa`, no en la key del widget:
al ocultarse el control en una sección global, Streamlit descarta el estado de su key y la
selección se perdería al volver a una sección con filtro. La sección activa vive igual en
`st.session_state.seccion_activa`.

| Pestaña | Contenido | Fuente |
|---------|-----------|--------|
| Panorama | KPIs del periodo, variación y por marca | serie diaria + snapshot |
| Pulso | Serie larga de horas, con huecos donde faltan días | serie diaria larga |
| Tendencias | Ritmo diario del periodo actual | serie diaria |
| Intensidad | Media, mediana, percentiles, activación y segmentos (global + marca) | snapshot usuario×LE |
| Crecimiento | Growth accounting (global + marca) | panel histórico |
| Retención | Retención por cohorte | panel histórico |
| Abandono | Avance máximo por tramos (global + marca) | snapshot usuario×LE |
| Cursos | Cursos con más y menos usuarios con consumo, y top 5 de Δ horas | snapshot usuario×LE |
| Puente y callejón | Lift de retención por LE (puente = lift > 0, callejón = lift < 0) | panel histórico |
| Activación | Embudo de usuarios únicos, licencia a 5 h | roster + snapshot |

Activación es la única sección que no viene del deck.

**Estructura fija de cada sección:** `encabezado()` (título + una línea con fecha de corte,
periodo, fuente y marca) y `glosario()` (expander «Cómo leer esto»: qué muestra, cómo se
calcula, definiciones). No hay más texto: sin captions de lectura ni cifras sueltas.

**Fecha de corte** = último día con dato en la serie del periodo actual (`meta["corte"]`,
`pipeline._fecha_corte`). Las etiquetas de periodo usan meses en español (`MES_ABR`).

Las 10 secciones se prueban con `streamlit.testing.v1.AppTest`, con y sin filtro de marca.

### El dashboard es 100% descriptivo

**No lleva interpretación ni decisiones.** Se eliminó el helper `titular()` y sus 16 llamadas,
y se limpiaron glosarios y captions de juicios, diagnósticos y recomendaciones. Lo que queda es
dato, definición y método de cálculo. Las conclusiones y las decisiones viven en
`FABLE-5-ANALYSIS.md` y en los decks del comité, no en la app.

Desde el 30-Sep-2026 tampoco quedan los `st.caption` con cifras sueltas (pico de la serie,
retorno en +1, saldo neto, dispersión entre marcas, media/mediana): solo título, corte,
fuente y el bloque «Cómo leer esto».

**Regla al añadir secciones:** ningún texto de UI debe afirmar causa («el problema es…»),
valorar («solo», «apenas», «la ruta es la plataforma») ni sugerir acción («hay que», «es
decisión de…»). El color de signo (`color_signo`) es la única lectura de bueno/malo, y sale
del dato, no de una frase.

**Esta vista es CEO-facing.** Por eso no lleva el botón «Recargar datos» ni las
instrucciones de actualización semanal: son tarea del equipo de datos, no del lector. Para
refrescar los números, reemplazar los CSV (ver más arriba) y reiniciar la app.

## Memoria: por qué el dashboard usa `category` (no tocar sin medir)

El 23-Sep-2026 la app desplegada se cayó en Streamlit Community Cloud: renderizaba bien y a los
dos minutos moría con `healthz: EOF`, sin traceback. Era OOM, no un error de código.

La causa: las columnas de texto se leían como `object`, donde cada celda es un `str` de Python.
El snapshot de Marzo pesaba **233 MB para 296 k filas (786 bytes por fila)** aunque `Nombre de
la LE` tuviera 95 valores distintos y `Certificado` solo 2. Los 8 periodos juntos: **1.19 GB**,
por encima del límite de la plataforma.

El arreglo vive en `pipeline._compactar` / `_leer_parquet`:

- `COLS_CATEGORIA` pasa a `category` las 10 columnas de baja cardinalidad. 786 → **19 bytes por
  fila**, los 8 periodos de 1.19 GB a **35 MB**.
- Se lee con `pyarrow.Table.to_pandas(categories=...)`, no con `pd.read_parquet`. El parquet ya
  guarda estas columnas dictionary-encoded; pasar por `object` y compactar después producía un
  pico transitorio de ~230 MB por archivo, que era justo lo que mataba el proceso.
- **El orden de categorías se normaliza a alfabético.** `groupby(observed=True)` ordena los
  grupos por el orden de la categoría, y leyendo con pyarrow ese orden es el del diccionario
  interno del archivo: sin normalizar, el orden de las tablas dependía de cómo quedó escrito el
  parquet.
- **Los `float` no se tocan.** Bajarlos a `float32` ahorraba 2 MB de 233 y convertía `2694.96`
  en `2694.959961`. Esas cifras van a la pantalla del comité.

Reglas que hay que respetar al escribir código nuevo sobre estos frames:

- **Todo `groupby` lleva `observed=True`.** Sin él, pandas 2.x usa `observed=False` con
  categóricas y devuelve el producto cartesiano de todas las categorías; pandas 3.0 cambió el
  default a `True`. Explícito = mismo resultado en las dos versiones.
- **Un tramo o etiqueta que se convierte a número pasa por `_avance()`**, que fuerza numérico.
  `.map()` sobre una categórica devuelve otra categórica y un `.max()` posterior truena.
- **Los frames ya agregados (decenas de filas) van por `_descat()`** antes de un `merge` externo
  o un `fillna`: ahí `category` no ahorra nada y rompe (`Cannot setitem on a Categorical with a
  new category`).
- Los caches de `app.py` tienen tope (`max_entries`): sin él, pasear por las 4 marcas dejaba 5
  resultados completos vivos a la vez.

Cualquier cambio en el pipeline se valida con un digest completo de `computar` (todas las
marcas, todas las secciones) comparado contra el estado anterior: el arreglo entero se hizo
verificando que el hash no cambiara ni un dígito.

## Arquitectura

- **`pipeline.py`**: motor de datos puro (sin Streamlit). Replica celda por celda las
  definiciones canónicas del comité: filtro de test, mapa de marcas, tramos, segmentos
  por horas, growth accounting, cohortes y lift de retención. Es la única pieza que hay
  que mantener sincronizada si el notebook cambia una definición.
- **`app.py`**: UI Streamlit con gráficas Plotly interactivas y navegación por secciones.

### Reglas de la capa visual (no romperlas al añadir gráficas)

- **El color no decora.** Violeta de marca (`MORADO`, #7D17E6) = periodo actual, gris = periodo
  anterior. Verde y rojo solo para signo, vía `color_signo()`. El **magenta de marca**
  (#E3327E) es acento: resalta una selección o una referencia y **nunca significa bueno ni
  malo**, porque compartiría lectura con el rojo del signo. Las marcas no tienen color propio:
  cuando lo tenían, naranja y verde se leían como semáforo sin significarlo.
- **Paleta e identidad.** Los tonos se tomaron del asset de marca (gradiente violeta a
  magenta). Las escalas secuenciales usan `ESCALA_MARCA` (lila claro a violeta profundo), no
  las paletas por defecto de Plotly. `AZUL`/`AZUL_CLARO` siguen existiendo como alias de
  `MORADO`/`MORADO_CLARO` para no reescribir cada gráfica.
- **El tema se fija en `.streamlit/config.toml`**, no solo en CSS: sin él Streamlit sigue el
  modo claro/oscuro del sistema de quien abre el tablero, y en oscuro el texto en tinta
  violeta quedaba ilegible.
- **Montserrat va empotrada en base64** desde `assets/fonts/Montserrat-variable.woff2`
  (`_css_fuente()`), así que no depende de la red ni de que esté instalada en la máquina que
  abre el dashboard. Google la sirve como fuente variable: un solo archivo cubre todos los pesos.
- **Los deltas van por `delta_txt()`**, con el signo al inicio de la cadena y sin glifos de
  flecha delante. Con un `▼` al frente, `st.metric` no reconoce el signo y pinta las caídas
  en verde con flecha hacia arriba.
- **Dos paneles lado a lado comparten escala**, o barras del mismo largo representan
  magnitudes distintas. Aplica a gancho/callejón y a subidas/caídas de cursos.
- **Un panel por métrica, no por marca.** Los ejes por universidad no eran comparables.
  Los ejes de conteos arrancan en cero (`rangemode="tozero"`).
- **Nombres de LE con `corto()`** y el nombre completo en el `hovertemplate`.
- **Sin em-dash** en código, docstrings, títulos de gráfica ni textos de UI.
- La ventana de export es de 30 días corridos, no un mes calendario: decir **«periodo»**.
- **Media Y mediana, siempre que haya distribución.** El top 5% de usuarios concentra la mitad
  de las horas: la media describe a esa cola y la mediana al alumno real. Reportar solo la
  media hace que una meta se pueda cumplir moviendo únicamente a los power users.
- **Los conteos de la serie diaria son usuario-día, no personas.** «Activos» y «efectivos»
  suman conteos diarios: nunca ponerlos en un embudo de personas ni compararlos con los
  usuarios únicos del snapshot.
- **`Certificado` es resultado, no palanca.** Es del par (usuario, LE), no del curso: 99 de
  112 LEs tienen filas `Si` y `No`. No presentarlo como una característica del catálogo.

> ⚠️ **Nota de medición** (heredada del deck): los KPIs de panorama salen de la *serie
> diaria de plataforma* y la segmentación del *snapshot usuario×LE*; reportan universos
> distintos (la serie diaria mide ~3× las horas). Nunca sumar ni cruzar ambos números.
