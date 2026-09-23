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

Navegación y filtro viven en la barra superior (`st.segmented_control`), no en el sidebar.
Son **tres filas**: grupo, sección dentro del grupo y marca.

Los grupos agrupan por el objeto que miden: **Periodo**, **Usuarios** y **Contenido**. Con 16
secciones en una sola fila la barra se volvía ilegible, por eso la navegación es de dos niveles.

**El filtro de marca solo aparece donde cambia los números.** Tendencias y Pulso se
calculan sobre la serie diaria de plataforma, que el proveedor no desglosa por universidad
(`SIN_MARCA` en `app.py`), así que ahí el control se oculta y una nota explica por qué.

En **Panorama** el filtro sí está, y **cambia la fuente de los KPIs**:

| Filtro | Fuente | KPIs |
|--------|--------|------|
| `Todas` | serie diaria de plataforma | 4 (incluye usuarios efectivos) |
| una universidad | snapshot usuario×LE de esa marca | 3 (horas, contenidos, usuarios con consumo) |

Los dos juegos **no son comparables entre sí**: miden universos distintos (la serie diaria
reporta ~3x las horas del snapshot). Nunca se muestran en la misma fila, y el `caption` y el
glosario dicen en cada caso de dónde salen los números. Sin esto el filtro habría sido
decorativo en Panorama, o peor: los 4 KPIs globales parecerían ser de la marca elegida.

Los bloques «Por marca» son comparaciones y **siempre muestran las cuatro universidades**,
con la seleccionada resaltada y las demás a menor opacidad. Filtrarlos a una sola dejaba una
barra huérfana; en Profundidad, además, la dispersión entre marcas se calculaba sobre una
única fila (max - min = 0), así que el caption reportaba una brecha de 0 puntos sin nada que
comparar.

La marca elegida se guarda en `st.session_state.marca_activa`, no en la key del widget:
al ocultarse el control en una sección global, Streamlit descarta el estado de su key y la
selección se perdería al volver a una sección con filtro.

| Grupo | Pestaña | Contenido | Fuente |
|-------|---------|-----------|--------|
| Periodo | Resumen | Los 3 KPIs de cabecera y dónde se detalla cada uno | snapshot + roster + panel |
| Periodo | Panorama | KPIs del periodo, variación y por marca | serie diaria + snapshot |
| Periodo | Certificación | Certificados obtenidos, tasa por alumno y evolución | snapshot usuario×LE |
| Periodo | Pulso | Serie larga anotada | serie diaria larga |
| Usuarios | Activación | Embudo de usuarios únicos y activos vs efectivos | roster + snapshot |
| Usuarios | Profundidad | Activación, intensidad, media contra mediana y concentración | snapshot usuario×LE |
| Usuarios | Abandono | Avance máximo por tramos | snapshot usuario×LE |
| Usuarios | Retención | Retención por cohorte | panel histórico |
| Usuarios | Crecimiento | Growth accounting (global + marca) | panel histórico |
| Usuarios | Tendencias | Ritmo diario del periodo actual | serie diaria |
| Usuarios | Centro y Nivel | Activación sobre licencias por centro y nivel | snapshot + roster |
| Contenido | Cursos | Top/bottom LEs por horas y por Δ | snapshot usuario×LE |
| Contenido | Catálogo | Uso contra fecha de creación, cursos dormidos | snapshot usuario×LE |
| Contenido | Formato | Horas por inscripción según plantilla de curso | snapshot usuario×LE |
| Contenido | Ruta Máster | Los 18 cursos de la ruta: avance y cobertura | snapshot usuario×LE |
| Contenido | Lift | Lift de retención por LE (gancho vs callejón) | panel histórico |

Las 16 secciones se prueban con `streamlit.testing.v1.AppTest`, con y sin filtro de marca.

### El dashboard es 100% descriptivo

**No lleva interpretación ni decisiones.** Se eliminó el helper `titular()` y sus 16 llamadas,
y se limpiaron glosarios y captions de juicios, diagnósticos y recomendaciones. Lo que queda es
dato, definición y método de cálculo. Las conclusiones y las decisiones viven en
`FABLE-5-ANALYSIS.md` y en los decks del comité, no en la app.

Al quitar un titular que traía una cifra ausente de las gráficas, esa cifra se conservó como
`st.caption` neutro: pico de la serie larga, retorno en +1 de las cohortes, saldo neto de
growth accounting, tasa de certificación entre los que llegan al 80-100%, rango de activación
por centro y peso de la Ruta Máster.

**Regla al añadir secciones:** ningún texto de UI debe afirmar causa («el problema es…»),
valorar («solo», «apenas», «la ruta es la plataforma») ni sugerir acción («hay que», «es
decisión de…»). El color de signo (`color_signo`) es la única lectura de bueno/malo, y sale
del dato, no de una frase.

**Esta vista es CEO-facing.** Por eso no lleva el botón «Recargar datos» ni las
instrucciones de actualización semanal: son tarea del equipo de datos, no del lector. Para
refrescar los números, reemplazar los CSV (ver más arriba) y reiniciar la app.

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
