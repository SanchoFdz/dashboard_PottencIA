"""
Dashboard PottencIA / ODILO: versión interactiva del deck mensual del comité.

Reemplaza las presentaciones fijas (Datos PottencIA - <fecha>.pptx). Se actualiza
solo con reemplazar los CSV que Santiago descarga del proveedor Odilo BI en las
carpetas mnt/data/current, mnt/data/previous y datos_analisis_estrategico_2026.

Cada sección lleva solo título, fecha de corte, fuente y el bloque «Cómo leer
esto» (qué muestra, cómo se calcula, definiciones). Nada interpretativo.

Ejecutar:  streamlit run dashboard/app.py
"""

import base64
import os

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import pipeline as pl

st.set_page_config(page_title="PottencIA · Dashboard", page_icon="📊",
                   layout="wide", initial_sidebar_state="expanded")


# ---- Paleta de marca PottencIA ----
# Los tonos salen del propio asset de marca (gradiente violeta -> magenta).
# La regla no cambia: el color NO decora. MORADO = periodo actual, gris = periodo
# anterior, verde/rojo SOLO para signo. El MAGENTA es acento de marca y se
# reserva para resaltar la seleccion o una referencia; nunca significa "bueno"
# ni "malo", porque compartiria lectura con el rojo del signo.
MORADO = "#7D17E6"          # violeta del gradiente (serie actual)
MORADO_CLARO = "#B47BF0"    # tinte del mismo violeta (serie secundaria)
MAGENTA = "#E3327E"         # magenta del gradiente (acento de marca)
VERDE = "#12855A"
ROJO = "#B42318"
GRIS = "#8A8296"            # neutro violaceo, no azulado
GRIS_PREV = "#D9D3E2"       # periodo anterior
TINTA = "#1A0B2E"           # violeta casi negro, el fondo de la marca
SEG_COLORS = {"Exploradores": "#EDE4FA", "Constantes": "#C9A7E8",
              "Intensivos": "#9B4FD1", "Power users": "#5B0FA8"}
# Tramos de avance: misma rampa secuencial que los segmentos (orden, no juicio).
TRAMO_COLORS = {10: "#EDE4FA", 35: "#C9A7E8", 65: "#9B4FD1", 90: "#5B0FA8"}
TRAMO_LBL = {10: "0-20%", 35: "20-50%", 65: "50-80%", 90: "80-100%"}
# Escala secuencial de marca para el mapa de calor de cohortes.
ESCALA_MARCA = [[0.0, "#F6F1FD"], [0.5, "#B47BF0"], [1.0, "#5B0FA8"]]

# Alias historicos: el codigo del deck hablaba de AZUL porque la paleta anterior
# era azul. Se conservan para no reescribir cada grafica.
AZUL, AZUL_CLARO = MORADO, MORADO_CLARO


_FUENTE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                      "assets", "fonts", "Montserrat-variable.woff2")


@st.cache_data
def _css_fuente() -> str:
    """Montserrat empotrada en base64: sin depender de la red ni de que la
    fuente este instalada en la maquina que abre el dashboard."""
    if not os.path.exists(_FUENTE):
        return ""
    b64 = base64.b64encode(open(_FUENTE, "rb").read()).decode()
    return (f"@font-face {{font-family:'Montserrat';font-style:normal;"
            f"font-weight:100 900;font-display:swap;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2');}}")


st.markdown(f"""
<style>
  {_css_fuente()}
  html, body, [class*="css"], .stMarkdown, button, input, textarea, select {{
      font-family: 'Montserrat', 'Helvetica Neue', Helvetica, Arial, sans-serif;
  }}
  .block-container {{padding-top: 4.5rem; max-width: 1500px;}}
  h1 {{font-size: 1.95rem !important; letter-spacing: -0.02em; font-weight: 800;
      color: {TINTA};}}
  h2 {{font-size: 1.22rem !important; font-weight: 700; margin-top: 2.2rem; color: {TINTA};}}
  h3 {{font-size: 1.0rem !important; font-weight: 600; color: #5B4A73;}}
  /* Los valores de KPI mandan; la etiqueta acompanna. */
  [data-testid="stMetricValue"] {{font-size: 2.1rem; font-weight: 700; color: {TINTA};}}
  [data-testid="stMetricLabel"] p {{font-size: 0.86rem; color: #6B6280;}}
  [data-testid="stMetricDelta"] {{font-size: 0.92rem;}}
  /* El glosario es apoyo, no protagonista. */
  [data-testid="stExpander"] summary p {{font-size: 0.86rem; color: #6B6280;}}
  [data-testid="stExpander"] details {{border-color: #E7E1F0;}}
  hr {{margin: 0.9rem 0 1.4rem 0;}}
  /* La barra de navegacion toma el violeta de marca al seleccionar. */
  [data-testid="stSegmentedControl"] button[aria-checked="true"],
  [data-baseweb="segmented-control"] [aria-selected="true"] {{
      background: {MORADO} !important; color: white !important;
  }}
  section[data-testid="stSidebar"] {{background: #FBF9FE;}}
</style>
""", unsafe_allow_html=True)


def color_signo(v):
    """Verde si sube, rojo si baja. Unico uso legitimo de verde/rojo."""
    return VERDE if v > 0 else (ROJO if v < 0 else GRIS)


# ---- Estilo unificado: fondo BLANCO + rejilla tenue ----
def show(fig, height=420):
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="white", plot_bgcolor="white",
        font=dict(size=13, color=TINTA, family="Montserrat, Helvetica, Arial"),
        margin=dict(l=45, r=25, t=55, b=45),
        height=height,
        legend=dict(bgcolor="rgba(255,255,255,0.7)", bordercolor="#E7E1F0", borderwidth=1),
        title_font=dict(size=15),
    )
    if fig.layout.title.text is None:
        fig.update_layout(title_text="")
    # Sin esto, el texto "outside" de las barras altas se recorta contra el eje.
    fig.update_traces(cliponaxis=False, selector=dict(type="bar"))
    fig.update_xaxes(gridcolor="#F0EBF7", zerolinecolor="#DFD8EA", linecolor="#DFD8EA")
    fig.update_yaxes(gridcolor="#F0EBF7", zerolinecolor="#DFD8EA", linecolor="#DFD8EA")
    st.plotly_chart(fig, use_container_width=True)


def glosario(que_es: str, como_se_calcula: str, terminos: dict | None = None):
    """Bloque de contexto que acompaña a cada gráfica: dato y definición, sin lectura."""
    with st.expander("Cómo leer esto, cómo se calcula, glosario", expanded=False):
        st.markdown(f"**Qué muestra:** {que_es}")
        st.markdown(f"**Cómo se calcula:** {como_se_calcula}")
        if terminos:
            st.markdown("**Glosario**")
            for k, v in terminos.items():
                st.markdown(f"- **{k}:** {v}")


def corto(nombre, n=46):
    """Nombres de LE truncados: sin esto se comen la mitad del ancho util."""
    s = str(nombre)
    return s if len(s) <= n else s[:n - 3].rstrip() + "..."


def fmt(v, dec=0):
    if pd.isna(v):
        return "s/d"
    return f"{v:,.{dec}f}"


def delta_txt(delta, sufijo="% vs periodo anterior", dec=1):
    """Texto de delta para st.metric.

    Streamlit colorea segun el signo que encuentra al inicio de la cadena, asi
    que el numero va con signo explicito y SIN glifos de flecha delante: con un
    "▼" al frente Streamlit no reconocia el signo y pintaba las caidas en verde
    con flecha hacia arriba.
    """
    if pd.isna(delta):
        return None
    return f"{delta:+.{dec}f}{sufijo}"


# ==================================================================
# Carga de datos (base pesada cacheada; agregados por marca al vuelo)
# ==================================================================
# max_entries=1: la base es una sola y pesada; no tiene sentido guardar copias.
@st.cache_data(show_spinner="Cargando datos…", max_entries=1)
def load_base(_token: float):
    return pl.cargar_base()


# max_entries=2: sin tope, pasear por las 4 marcas dejaba 5 resultados completos
# vivos a la vez. Recalcular cuesta ~1s, la memoria en Cloud cuesta la app.
@st.cache_data(show_spinner="Calculando agregados…", max_entries=2)
def compute(_token: float, marcas_key: tuple):
    base = load_base(_token)
    marcas = list(marcas_key) if marcas_key else None
    return pl.computar(base, marcas)


# ==================================================================
# Sidebar
# ==================================================================
st.sidebar.title("PottencIA")
st.sidebar.caption("Dashboard de monitoreo | Fuente: ODILO")

# El token de recarga sigue existiendo (lo consumen los caches), pero sin boton:
# esta vista es CEO-facing. Para refrescar: reiniciar la app tras reemplazar los CSV.
if "reload_token" not in st.session_state:
    st.session_state.reload_token = 0.0

try:
    BASE = load_base(st.session_state.reload_token)
except FileNotFoundError as e:
    st.error(f"No se encontraron los CSV esperados.\n\n{e}\n\n"
             "Revisa que `mnt/data/current`, `mnt/data/previous` y "
             "`datos_analisis_estrategico_2026` contengan los exports del proveedor.")
    st.stop()

meta = BASE["meta"]
CORTE = meta.get("corte", "s/d")
EJES = ", ".join(meta.get("ejes", []))

st.sidebar.markdown(f"**Fecha de corte:** {CORTE}")
st.sidebar.markdown(f"**Periodo actual:** {meta['cur_label']}")
st.sidebar.markdown(f"**Periodo anterior:** {meta['prev_label']}")

# ==================================================================
# Navegación y filtro (barra superior)
# ==================================================================
# Una sola fila, en el orden del deck del comité. Activación es la única
# sección que no viene del deck.
SECCIONES = ["Panorama", "Pulso", "Tendencias", "Intensidad", "Crecimiento",
             "Retención", "Abandono", "Cursos", "Puente y callejón", "Activación"]
TITULOS = {
    "Panorama": "Panorama del periodo",
    "Pulso": "Pulso de la plataforma",
    "Tendencias": "Tendencias diarias del periodo actual",
    "Intensidad": "Intensidad y segmentación de uso",
    "Crecimiento": "Crecimiento de la base de usuarios",
    "Retención": "Retención por cohorte",
    "Abandono": "Avance máximo en los cursos",
    "Cursos": "Cursos con más y menos usuarios",
    "Puente y callejón": "Cursos puente y callejón",
    "Activación": "Embudo de activación",
}

if "seccion_activa" not in st.session_state:
    st.session_state.seccion_activa = SECCIONES[0]
seccion = st.segmented_control("Sección", SECCIONES, default=st.session_state.seccion_activa,
                               label_visibility="collapsed", key="nav_seccion")
if seccion is None:
    seccion = st.session_state.seccion_activa
st.session_state.seccion_activa = seccion

TODAS = "Todas"

# Secciones SIN dimension de marca: salen de la serie diaria de plataforma, que
# el proveedor no desglosa por universidad. Ahi el filtro no cambiaria ni un
# numero, asi que no se muestra.
SIN_MARCA = {"Tendencias", "Pulso"}

# La seleccion se guarda aparte del widget: al ocultarlo en una seccion global,
# Streamlit descarta el estado de su key y se perderia al volver.
if "marca_activa" not in st.session_state:
    st.session_state.marca_activa = TODAS

if seccion in SIN_MARCA:
    marca_sel = TODAS
else:
    marca_sel = st.segmented_control(
        "Marca", [TODAS] + BASE["marcas"], default=st.session_state.marca_activa,
        label_visibility="collapsed", key=f"marca_{seccion}")
    if marca_sel is None:
        marca_sel = TODAS
    st.session_state.marca_activa = marca_sel

es_global = marca_sel == TODAS
marcas_key = None if es_global else (marca_sel,)

R = compute(st.session_state.reload_token, marcas_key)

etiqueta_marca = "todas las marcas" if es_global else marca_sel
st.divider()


def encabezado(fuente: str, periodo: str | None = None):
    """Título + una línea de metadatos: corte, periodo, fuente y marca."""
    st.header(TITULOS[seccion])
    periodo = periodo or (f"Periodo actual {meta['cur_label']} · "
                          f"anterior {meta['prev_label']}")
    marca = "global, sin desglose por marca" if seccion in SIN_MARCA else etiqueta_marca
    st.caption(f"Corte: {CORTE} · {periodo} · Fuente: {fuente} · {marca}")


PERIODOS_PANEL = f"Periodos del panel: {EJES}"


def _opacidad(universidades, base=0.35):
    """Marca elegida a opacidad plena, las demás atenuadas (nunca ocultas)."""
    return [1.0 if (es_global or u == marca_sel) else base for u in universidades]


# ==================================================================
# PANORAMA
# ==================================================================
if seccion == "Panorama":
    # Los KPIs cambian de FUENTE segun el filtro, porque la serie diaria de
    # plataforma no trae desglose por universidad:
    #   - Todas  -> serie diaria de plataforma (4 KPIs, incluye efectivos).
    #   - 1 marca -> snapshot usuario x LE de esa marca (3 KPIs).
    # Nunca se mezclan en la misma fila: los universos son distintos.
    if es_global:
        encabezado("serie diaria de plataforma (KPIs) y snapshot usuario×LE (por marca)")
        pan = R["panorama"]
        glosario(
            "Los 4 KPIs de cabecera del periodo, su variación contra el periodo anterior y "
            "los mismos KPIs por universidad.",
            "Suma de la **serie diaria de plataforma** del periodo. Δ% = (actual − anterior) / "
            "anterior. Usuarios efectivos se divide entre 2 (corrección de doble conteo heredada "
            "del deck). El bloque «Por marca» sale del snapshot usuario×LE.",
            {"Horas consumidas": "suma de horas de aprendizaje del periodo.",
             "Contenidos únicos": "recursos distintos consumidos (DISTINCT_COUNT).",
             "Usuarios activos": "cualquier interacción registrada en el periodo.",
             "Usuarios efectivos": "usuarios con consumo real (métrica más estricta del portal).",
             "Serie diaria vs snapshot": "miden universos distintos (la serie diaria reporta "
                                         "~3x las horas del snapshot); sus valores no se suman "
                                         "ni se comparan entre sí."})
    else:
        encabezado("snapshot usuario×LE")
        _fila = R["panorama_marca"]
        _fila = _fila[_fila["Universidad"] == marca_sel]
        pan = pd.DataFrame([
            {"kpi": "Horas consumidas", "actual": float(_fila["Horas_actual"].iloc[0]),
             "anterior": float(_fila["Horas_anterior"].iloc[0])},
            {"kpi": "Contenidos consumidos", "actual": float(_fila["Contenidos_actual"].iloc[0]),
             "anterior": float(_fila["Contenidos_anterior"].iloc[0])},
            {"kpi": "Usuarios con consumo", "actual": float(_fila["Usuarios_actual"].iloc[0]),
             "anterior": float(_fila["Usuarios_anterior"].iloc[0])},
        ])
        pan["delta_pct"] = np.where(pan["anterior"] > 0,
                                    (pan["actual"] / pan["anterior"] - 1) * 100, np.nan)
        glosario(
            f"Los KPIs de {marca_sel}, su variación contra el periodo anterior y la "
            "comparación con las demás universidades.",
            "Suma del **snapshot usuario×LE** de la marca. Δ% = (actual − anterior) / anterior. "
            "Con una universidad elegida la fuente es el snapshot, porque la serie diaria de "
            "plataforma no trae desglose por marca.",
            {"Horas consumidas": "suma de horas de la marca en el periodo.",
             "Contenidos consumidos": "suma de contenidos consumidos por la marca.",
             "Usuarios con consumo": "usuarios distintos de la marca con al menos un registro.",
             "Valores de «Todas» vs marca": "miden universos distintos (serie diaria vs "
                                            "snapshot); no son comparables entre sí."})

    cols = st.columns(len(pan))
    for col, (_, r) in zip(cols, pan.iterrows()):
        col.metric(r["kpi"], fmt(r["actual"]), delta_txt(r["delta_pct"]))

    # Los KPIs tienen unidades incomparables (horas, contenidos, personas),
    # asi que se grafica la VARIACION en %, que si es comparable entre ellos.
    pv = pan.dropna(subset=["delta_pct"]).sort_values("delta_pct")
    fig = go.Figure(go.Bar(
        x=pv["delta_pct"], y=pv["kpi"], orientation="h",
        marker_color=[color_signo(v) for v in pv["delta_pct"]],
        text=[f"{v:+.1f}%" for v in pv["delta_pct"]], textposition="outside",
        customdata=list(zip(pv["anterior"], pv["actual"])),
        hovertemplate="%{y}<br>Anterior %{customdata[0]:,.0f}<br>"
                      "Actual %{customdata[1]:,.0f}<br>Variación %{x:+.1f}%<extra></extra>"))
    _m = float(np.nanmax(np.abs(pv["delta_pct"]))) * 1.30
    if (pv["delta_pct"] < 0).all():
        _rango = [-_m, _m * 0.12]
    elif (pv["delta_pct"] > 0).all():
        _rango = [-_m * 0.12, _m]
    else:
        _rango = [-_m, _m]
    fig.update_layout(title="Variación de cada KPI contra el periodo anterior",
                      xaxis_title="% vs periodo anterior", xaxis_range=_rango)
    fig.add_vline(x=0, line=dict(color="#b7c0cc", width=1))
    show(fig, height=300)

    st.subheader("Por marca")
    pm = R["panorama_marca"]
    _op = _opacidad(pm["Universidad"])
    METRICAS = [("Horas", "Horas consumidas"), ("Contenidos", "Contenidos únicos"),
                ("Usuarios", "Usuarios")]
    fig2 = make_subplots(rows=1, cols=3, subplot_titles=[lbl for _, lbl in METRICAS])
    for i, (key, _lbl) in enumerate(METRICAS, start=1):
        fig2.add_trace(go.Bar(x=pm["Universidad"], y=pm[f"{key}_anterior"], name="Anterior",
                              marker=dict(color=GRIS_PREV, opacity=_op),
                              showlegend=(i == 1)), row=1, col=i)
        fig2.add_trace(go.Bar(x=pm["Universidad"], y=pm[f"{key}_actual"], name="Actual",
                              marker=dict(color=AZUL, opacity=_op),
                              showlegend=(i == 1)), row=1, col=i)
        fig2.update_yaxes(rangemode="tozero", row=1, col=i)
    fig2.update_layout(barmode="group", bargap=0.28)
    show(fig2, height=380)
    with st.expander("Ver tabla"):
        st.dataframe(pm, use_container_width=True, hide_index=True)


# ==================================================================
# PULSO (serie larga)
# ==================================================================
elif seccion == "Pulso":
    s = R["serie_larga"]
    encabezado("serie diaria de horas de plataforma",
               periodo=f"Serie {s['fecha'].min():%d-%m-%Y} a {s['fecha'].max():%d-%m-%Y}")
    glosario(
        "La serie diaria de horas de aprendizaje de la plataforma desde el primer día disponible.",
        "Panel superior: media móvil de 7 días y tendencia de 28 días. Panel inferior: índice = "
        "horas del día / tendencia 28d. Los días sin dato en las exportaciones quedan como hueco "
        "en la línea.",
        {"Media móvil 7d": "promedio del día y los 6 anteriores con dato.",
         "Tendencia 28d": "media móvil centrada de 28 días.",
         "Índice vs tendencia": "horas del día / tendencia 28d. 1 = igual a la tendencia.",
         "Carga masiva": "alta masiva de usuarios (Feb-2026), marcada en la serie."})

    # Se reindexa a calendario diario para que los dias ausentes en las
    # exportaciones se dibujen como hueco y no como una recta que los une.
    _cal = pd.DataFrame({"fecha": pd.date_range(s["fecha"].min(), s["fecha"].max(), freq="D")})
    sp = _cal.merge(s, on="fecha", how="left")

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.65, 0.35],
                        subplot_titles=["Horas de aprendizaje / día",
                                        "Índice vs tendencia 28d"])
    fig.add_trace(go.Scatter(x=sp["fecha"], y=sp["r7"], line=dict(color=AZUL, width=2),
                             name="Horas/día (7d)"), row=1, col=1)
    fig.add_trace(go.Scatter(x=sp["fecha"], y=sp["r28"], line=dict(color=GRIS, width=1.5, dash="dash"),
                             name="Tendencia 28d"), row=1, col=1)
    fig.add_trace(go.Scatter(x=sp["fecha"], y=sp["idx_estacional"], line=dict(color="#CFC3E4", width=0.5),
                             fill="tozeroy", name="Índice", showlegend=False), row=2, col=1)
    fig.add_hline(y=1, line=dict(color=GRIS, dash="dash"), row=2, col=1)
    for f, txt in [("2026-02-01", "Carga masiva")]:
        fdt = pd.to_datetime(f)
        if s["fecha"].min() <= fdt <= s["fecha"].max():
            fig.add_shape(type="line", x0=fdt, x1=fdt, yref="y domain", y0=0, y1=1,
                          line=dict(color=GRIS, width=1, dash="dot"), row=1, col=1)
            fig.add_annotation(x=fdt, yref="y domain", y=1, text=txt, textangle=-90,
                               showarrow=False, font=dict(size=9, color=GRIS),
                               xanchor="left", yanchor="top", row=1, col=1)
    show(fig, height=600)


# ==================================================================
# TENDENCIAS DIARIAS
# ==================================================================
elif seccion == "Tendencias":
    encabezado("serie diaria de plataforma")
    glosario(
        "El ritmo día a día del periodo actual y el promedio diario del periodo anterior.",
        "Línea = media móvil de 7 días de la serie diaria. Línea gris punteada = promedio "
        "diario del periodo anterior.",
        {"Media móvil 7d": "promedio de cada día con los 6 previos.",
         "Promedio periodo anterior": "promedio diario del periodo anterior, como referencia fija.",
         "Media y mediana por día": "de los valores diarios del periodo actual."})
    t = R["tendencias"]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        subplot_titles=["Horas consumidas / día", "Contenidos / día"])
    h, c = t["horas"], t["contenidos"]
    fig.add_trace(go.Scatter(x=h["fecha"], y=h["rolling_7d"], line=dict(color=AZUL, width=3),
                             name="Horas (7d)"), row=1, col=1)
    fig.add_hline(y=t["horas_prev_avg"], line=dict(color=GRIS, dash="dash"), row=1, col=1,
                  annotation_text="Promedio diario del periodo anterior",
                  annotation_position="top left",
                  annotation_font=dict(size=11, color=GRIS))
    fig.add_trace(go.Scatter(x=c["fecha"], y=c["rolling_7d"], line=dict(color=AZUL_CLARO, width=3),
                             name="Contenidos (7d)"), row=2, col=1)
    fig.add_hline(y=t["contenidos_prev_avg"], line=dict(color=GRIS, dash="dash"), row=2, col=1,
                  annotation_text="Promedio diario del periodo anterior",
                  annotation_position="top left",
                  annotation_font=dict(size=11, color=GRIS))
    show(fig, height=560)
    _hc = h["Horas de aprendizaje (SUM)"]
    _cc = c["cadenarecurso (DISTINCT_COUNT)"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Horas/día actual (media)", fmt(_hc.mean(), 0),
              f"mediana {_hc.median():,.0f}", delta_color="off")
    c2.metric("Horas/día periodo ant. (media)", fmt(t["horas_prev_avg"], 0))
    c3.metric("Contenidos/día actual (media)", fmt(_cc.mean(), 0),
              f"mediana {_cc.median():,.0f}", delta_color="off")
    c4.metric("Contenidos/día periodo ant. (media)", fmt(t["contenidos_prev_avg"], 0))


# ==================================================================
# INTENSIDAD Y SEGMENTACIÓN
# ==================================================================
elif seccion == "Intensidad":
    encabezado("snapshot usuario×LE")
    glosario(
        "Horas por alumno activado (media, mediana y percentiles), el reparto entre no "
        "activados y activados, y los 4 niveles de intensidad entre los activados.",
        "Se suman las horas de cada usuario en el periodo y se clasifican por umbrales fijos. "
        "Los cortes de distribución se calculan sobre los usuarios activados.",
        {"No activados": "0 horas en el periodo.",
         "Activados": "más de 0 horas en el periodo.",
         "Exploradores": "más de 0 y hasta 1 h.", "Constantes": "más de 1 y hasta 5 h.",
         "Intensivos": "más de 5 y hasta 20 h.", "Power users": "más de 20 h.",
         "Mediana (p50)": "valor que deja a la mitad de los activados por debajo.",
         "p75 / p90": "valor que deja al 75% / 90% de los activados por debajo.",
         "Pasa de 20 min": "% de activados con 20 minutos o más en el periodo.",
         "Concentración top 5% / 1%": "% de las horas totales que suma el 5% / 1% de usuarios "
                                      "con más horas."})
    seg = R["segmentacion_global"]
    act, inten = seg["activacion"], seg["intensidad"]
    dc, dp = R["dist_cur"], R["dist_prev"]

    # Media Y mediana, siempre juntas (regla de la capa visual).
    k = st.columns(4)
    k[0].metric("Mediana del activado", f"{dc['mediana_act']*60:.0f} min",
                delta_txt((dc["mediana_act"] - dp["mediana_act"]) * 60,
                          sufijo=" min vs periodo anterior", dec=0))
    k[1].metric("Media del activado", f"{dc['media_act']*60:.0f} min",
                delta_txt((dc["media_act"] - dp["media_act"]) * 60,
                          sufijo=" min vs periodo anterior", dec=0))
    k[2].metric("Pasa de 20 min", f"{dc['pct_ge20min']:.1f}%",
                delta_txt(dc["pct_ge20min"] - dp["pct_ge20min"],
                          sufijo=" pp vs periodo anterior"))
    k[3].metric("Concentración top 5%", f"{dc['share_top5']:.0f}% de las horas",
                f"top 1%: {dc['share_top1']:.0f}%", delta_color="off")

    _p = pd.DataFrame({
        "corte": ["Mediana (p50)", "p75", "p90", "Media"],
        "min": [dc["mediana_act"] * 60, dc["p75_act"] * 60, dc["p90_act"] * 60,
                dc["media_act"] * 60]})
    figp = go.Figure(go.Bar(x=_p["min"], y=_p["corte"], orientation="h",
                            marker_color=[AZUL, AZUL, AZUL, GRIS],
                            text=[f"{v:.0f} min" for v in _p["min"]], textposition="outside"))
    figp.update_layout(title="Minutos por alumno activado en el periodo",
                       xaxis_title="Minutos",
                       xaxis_range=[0, float(_p["min"].max()) * 1.3],
                       yaxis=dict(autorange="reversed"))
    show(figp, height=300)

    _noact = float(act.get("No activados", float("nan")))
    c1, c2 = st.columns([1, 1.6])
    with c1:
        st.metric("Usuarios activados", f"{(1-_noact)*100:.1f}%")
        # Barra apilada en lugar de dona: la dona rotaba la etiqueta 90 grados.
        fig1 = go.Figure()
        fig1.add_trace(go.Bar(y=["Base"], x=[(1 - _noact) * 100], orientation="h",
                              name="Activados", marker_color=AZUL,
                              text=[f"Activados {(1-_noact)*100:.1f}%"],
                              textposition="inside", insidetextfont=dict(color="white")))
        fig1.add_trace(go.Bar(y=["Base"], x=[_noact * 100], orientation="h",
                              name="No activados", marker_color=GRIS_PREV,
                              text=[f"No activados {_noact*100:.1f}%"], textposition="inside",
                              insidetextfont=dict(color=TINTA)))
        fig1.update_layout(barmode="stack", showlegend=False,
                           xaxis=dict(range=[0, 100], title="% de la base"),
                           yaxis=dict(showticklabels=False))
        show(fig1, height=170)
    with c2:
        fig2 = go.Figure(go.Bar(x=list(inten.values * 100), y=list(inten.index), orientation="h",
                                marker_color=[SEG_COLORS[s] for s in inten.index],
                                text=[f"{v*100:.1f}%" for v in inten.values],
                                textposition="outside"))
        fig2.update_layout(title="Intensidad entre los activados",
                           yaxis=dict(categoryorder="array", categoryarray=pl.SEG_ORDER[::-1]),
                           xaxis_title="% de activados",
                           xaxis_range=[0, float(inten.max()) * 118])
        show(fig2, height=330)

    st.subheader("Por marca")
    sm = R["segmentacion_marca"]
    if not sm.empty:
        fig3 = go.Figure()
        _op = _opacidad(sm["Universidad"])
        for s in pl.SEG_ORDER:
            fig3.add_trace(go.Bar(name=s, x=sm["Universidad"], y=sm[s] * 100,
                                  marker=dict(color=SEG_COLORS[s], opacity=_op)))
        fig3.update_layout(barmode="stack", yaxis_title="% de activados", bargap=0.45)
        show(fig3, height=300)
        with st.expander("Ver tabla (incluye % No activados)"):
            st.dataframe(sm, use_container_width=True, hide_index=True)


# ==================================================================
# CRECIMIENTO (growth accounting)
# ==================================================================
elif seccion == "Crecimiento":
    encabezado("panel histórico de snapshots usuario×LE", periodo=PERIODOS_PANEL)
    glosario(
        "Composición de los usuarios activos de cada periodo: nuevos, recurrentes y "
        "reactivados, y los perdidos respecto al periodo anterior.",
        "Cada usuario activo (más de 0 h) de un periodo se clasifica según su historial. "
        "«Periodo anterior» es el que le precede en la lista de periodos del panel.",
        {"Nuevos": "activos por primera vez en el panel.",
         "Recurrentes": "activos en este periodo y en el anterior.",
         "Reactivados": "activos en algún periodo previo, pero no en el anterior.",
         "Perdidos": "activos en el periodo anterior y no en este (línea bajo cero).",
         "Periodos del panel": f"{EJES}. Cada uno es un snapshot mensual o una ventana de "
                               "export etiquetada por su punto medio."})
    ga = R["growth"]

    fig = go.Figure()
    for col, color in [("Recurrentes", "#5B0FA8"), ("Reactivados", "#9B4FD1"), ("Nuevos", "#D9C2F2")]:
        fig.add_trace(go.Bar(name=col, x=ga["eje"], y=ga[col], marker_color=color))
    fig.add_trace(go.Scatter(name="Perdidos", x=ga["eje"], y=-ga["Perdidos"],
                             line=dict(color=ROJO, width=2), mode="lines+markers"))
    fig.update_layout(barmode="stack", yaxis_title="Usuarios")
    show(fig, height=460)

    ga2 = ga.copy()
    ga2["% recurrentes"] = (ga2["Recurrentes"] / ga2["Total activos"] * 100).round(0)
    st.dataframe(ga2[["eje", "Nuevos", "Recurrentes", "Reactivados", "Total activos",
                      "Perdidos", "% recurrentes"]], use_container_width=True, hide_index=True)

    st.subheader("Por marca")
    gm = R["growth_marca"]
    _titulos = [(f"▸ {m}" if (not es_global and m == marca_sel) else m) for m in gm.keys()]
    fig2 = make_subplots(rows=2, cols=2, subplot_titles=_titulos)
    for (marca, g), (rr, cc) in zip(gm.items(), [(1, 1), (1, 2), (2, 1), (2, 2)]):
        _op = 1.0 if (es_global or marca == marca_sel) else 0.4
        for col, color in [("Recurrentes", "#5B0FA8"), ("Reactivados", "#9B4FD1"), ("Nuevos", "#D9C2F2")]:
            fig2.add_trace(go.Bar(name=col, x=g["eje"], y=g[col],
                                  marker=dict(color=color, opacity=_op),
                                  showlegend=(rr == 1 and cc == 1)), row=rr, col=cc)
    fig2.update_layout(barmode="stack")
    show(fig2, height=620)


# ==================================================================
# RETENCIÓN (cohortes)
# ==================================================================
elif seccion == "Retención":
    encabezado("panel histórico de snapshots usuario×LE", periodo=PERIODOS_PANEL)
    glosario(
        "% de cada cohorte que sigue activa N periodos después de su primera actividad.",
        "Se agrupa a los usuarios por su periodo de primera actividad (cohorte) y se mide qué "
        "porcentaje tiene más de 0 h 1, 2, 3… periodos después. +0 siempre es 100%.",
        {"Cohorte": "usuarios cuya primera actividad cae en el mismo periodo.",
         "n": "tamaño de la cohorte (usuarios).",
         "+N": "N periodos después de la primera actividad, contados sobre la lista del panel.",
         "Periodos del panel": f"{EJES}."})
    coh = R["cohortes"]
    mcols = [c for c in coh.columns if c.startswith("m")]

    z = coh[mcols].values.astype(float) * 100
    fig = go.Figure(go.Heatmap(
        z=z, x=[f"+{i}" for i in range(len(mcols))],
        y=[f"{r.Cohorte} (n={int(r.n):,})" for r in coh.itertuples()],
        colorscale=ESCALA_MARCA, zmin=0, zmax=float(np.nanmax(z[:, 1:])) if z.shape[1] > 1 else 100,
        text=[[f"{v:.0f}" if not np.isnan(v) else "" for v in row] for row in z],
        texttemplate="%{text}", colorbar=dict(title="%")))
    fig.update_layout(title="% de la cohorte activo", yaxis=dict(autorange="reversed"),
                      xaxis_title="Periodos desde la primera actividad")
    show(fig, height=430)

    figc = go.Figure()
    _tot = max(len(coh), 2)
    for i, r in enumerate(coh.itertuples()):
        ys = [getattr(r, c) * 100 if not pd.isna(getattr(r, c)) else None for c in mcols]
        # Rampa de marca: lila claro (cohorte vieja) a violeta profundo (reciente).
        _mix = 0.18 + 0.82 * (i / (_tot - 1))
        _col = f"rgb({int(233 - 142*_mix)},{int(223 - 208*_mix)},{int(250 - 82*_mix)})"
        figc.add_trace(go.Scatter(x=list(range(len(mcols))), y=ys, mode="lines+markers",
                                  line=dict(color=_col, width=2),
                                  marker=dict(color=_col, size=6), name=r.Cohorte))
    figc.update_layout(title="Curvas de retención", yaxis_title="% de la cohorte activo",
                       xaxis_title="Periodos desde la primera actividad")
    show(figc, height=420)


# ==================================================================
# ABANDONO (avance máximo)
# ==================================================================
elif seccion == "Abandono":
    encabezado("snapshot usuario×LE")
    glosario(
        "Reparto de los pares (usuario, curso) según el avance máximo alcanzado, periodo "
        "actual contra anterior y por universidad.",
        "Para cada par (usuario, curso) se toma su **máximo tramo** de avance y se cuenta "
        "cuántos pares caen en cada tramo.",
        {"Par (usuario, curso)": "una inscripción concreta de una persona a un curso.",
         "Tramo": "banda de avance reportada por el portal (0-20, 20-50, 50-80, 80-100%).",
         "Bajo 20%": "% de pares cuyo avance máximo está en el tramo 0-20%.",
         "80% o más": "% de pares cuyo avance máximo está en el tramo 80-100%."})
    ab, abp = R["abandono_cur"], R["abandono_prev"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Pares bajo 20%", f"{ab['pct_bajo20']*100:.1f}%",
              delta_txt((ab["pct_bajo20"] - abp["pct_bajo20"]) * 100, sufijo=" pp vs periodo ant."),
              delta_color="inverse")
    c2.metric("Pares en 80% o más", f"{ab['pct_alto80']*100:.1f}%",
              delta_txt((ab["pct_alto80"] - abp["pct_alto80"]) * 100, sufijo=" pp vs periodo ant."))
    c3.metric("Pares (usuario, curso)", fmt(len(ab["detalle"])))

    dc, dp = ab["dist_tramos"], abp["dist_tramos"]
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Anterior", x=[TRAMO_LBL.get(i, i) for i in dp.index],
                         y=dp.values * 100, marker_color=GRIS_PREV,
                         text=[f"{v*100:.0f}%" for v in dp.values], textposition="outside"))
    fig.add_trace(go.Bar(name="Actual", x=[TRAMO_LBL.get(i, i) for i in dc.index],
                         y=dc.values * 100, marker_color=AZUL,
                         text=[f"{v*100:.0f}%" for v in dc.values], textposition="outside"))
    fig.update_layout(barmode="group", yaxis_title="% de pares",
                      xaxis_title="Tramo de avance máximo")
    show(fig, height=430)

    st.subheader("Por marca (periodo actual)")
    am = R["abandono_marca"]
    if not am.empty:
        fig2 = go.Figure()
        _op = _opacidad(am["Universidad"])
        for t in (10, 35, 65, 90):
            fig2.add_trace(go.Bar(name=TRAMO_LBL[t], x=am["Universidad"], y=am[t] * 100,
                                  marker=dict(color=TRAMO_COLORS[t], opacity=_op),
                                  # Sin etiqueta en segmentos < 5%: no caben y se enciman.
                                  text=[f"{v*100:.0f}%" if v >= 0.05 else "" for v in am[t]],
                                  textposition="inside",
                                  hovertemplate="%{x}<br>" + TRAMO_LBL[t] +
                                                ": %{y:.1f}% de pares<extra></extra>"))
        fig2.update_layout(barmode="stack", yaxis_title="% de pares", yaxis_range=[0, 100],
                           bargap=0.45, legend_title_text="Tramo")
        show(fig2, height=340)
        with st.expander("Ver tabla"):
            _t = am.rename(columns={t: TRAMO_LBL[t] for t in TRAMO_LBL})
            for c in TRAMO_LBL.values():
                _t[c] = (_t[c] * 100).round(1)
            st.dataframe(_t, use_container_width=True, hide_index=True)


# ==================================================================
# CURSOS: más y menos usuarios, y variación de horas
# ==================================================================
elif seccion == "Cursos":
    encabezado("snapshot usuario×LE")
    glosario(
        "Cursos ordenados por número de usuarios con consumo en el periodo actual, y cursos "
        "con mayor subida y bajada de horas contra el periodo anterior.",
        "Usuarios = usuarios distintos con más de 0 h en el curso durante el periodo. Solo entran "
        "cursos con al menos 1 usuario con consumo en el periodo actual; los empates se ordenan "
        "por ID del curso. Δ horas = horas del periodo actual menos horas del anterior, solo "
        "cursos con 1 h o más en el periodo anterior.",
        {"Curso (LE)": "Learning Experience, un curso o club del catálogo.",
         "Usuarios con consumo": "usuarios distintos con más de 0 h en ese curso.",
         "Δ usuarios": "usuarios del periodo actual menos los del anterior.",
         "Δ horas": "horas del periodo actual menos las del anterior."})
    ul = R["top_les"]["usuarios"]
    if ul.empty:
        st.info("Sin cursos con consumo en esta selección.")
    else:
        _c_sel, _ = st.columns([1, 3])
        with _c_sel:
            n = st.selectbox("Cursos por lado", [5, 10, 15], index=1, key="n_cursos")
        k = st.columns(3)
        k[0].metric("Cursos con consumo", fmt(len(ul)))
        k[1].metric("Mediana de usuarios por curso", fmt(ul["usuarios_cur"].median()))
        k[2].metric("Cursos con 1 usuario", fmt((ul["usuarios_cur"] == 1).sum()))

        top = ul.head(n).iloc[::-1]
        bot = ul.tail(n).iloc[::-1]
        # Escala compartida entre los dos paneles (regla de la capa visual).
        lim = float(ul["usuarios_cur"].max()) * 1.25

        def _barras(df, titulo):
            f = go.Figure(go.Bar(
                x=df["usuarios_cur"], y=[corto(s) for s in df["Nombre de la LE"]],
                orientation="h", marker_color=AZUL,
                text=[fmt(v) for v in df["usuarios_cur"]], textposition="outside",
                customdata=list(zip(df["Nombre de la LE"], df["usuarios_prev"], df["horas_cur"])),
                hovertemplate="%{customdata[0]}<br>%{x:,.0f} usuarios<br>"
                              "Periodo anterior %{customdata[1]:,.0f}<br>"
                              "%{customdata[2]:,.1f} h<extra></extra>"))
            f.update_layout(title=titulo, xaxis_title="Usuarios con consumo",
                            xaxis_range=[0, lim])
            return f

        c1, c2 = st.columns(2)
        with c1:
            show(_barras(top, f"{n} cursos con más usuarios"), height=120 + 32 * n)
        with c2:
            show(_barras(bot, f"{n} cursos con menos usuarios"), height=120 + 32 * n)

        st.subheader("Variación de horas contra el periodo anterior")
        tl = R["top_les"]
        tm = tl["top_mejora"].iloc[::-1]
        # Invertido igual que tm para que la mayor caida quede ARRIBA en los dos paneles.
        bc = tl["bottom_caida"].iloc[::-1]
        # Escala compartida entre los dos paneles.
        _lim = float(np.nanmax(np.abs(np.concatenate(
            [tm["delta"].values, bc["delta"].values])))) * 1.35 if not bc.empty else None
        figm = go.Figure(go.Bar(x=tm["delta"], y=[corto(s) for s in tm["Nombre de la LE"]],
                                orientation="h", marker_color=VERDE,
                                text=[f"{v:+.0f}" for v in tm["delta"]], textposition="outside",
                                customdata=tm["Nombre de la LE"],
                                hovertemplate="%{customdata}<br>%{x:+,.1f} h<extra></extra>"))
        figm.update_layout(title="5 con mayor subida (Δ horas)",
                           xaxis_range=[0, _lim] if _lim else None,
                           xaxis_title="Δ horas vs periodo anterior")
        figc = go.Figure(go.Bar(x=bc["delta"], y=[corto(s) for s in bc["Nombre de la LE"]],
                                orientation="h", marker_color=ROJO,
                                text=[f"{v:+.0f}" for v in bc["delta"]], textposition="outside",
                                customdata=bc["Nombre de la LE"],
                                hovertemplate="%{customdata}<br>%{x:+,.1f} h<extra></extra>"))
        figc.update_layout(title="5 con mayor bajada (Δ horas)",
                           xaxis_range=[-_lim, 0] if _lim else None,
                           xaxis_title="Δ horas vs periodo anterior")
        c1, c2 = st.columns(2)
        with c1:
            show(figm, height=360)
        with c2:
            show(figc, height=360)

        with st.expander("Ver todos los cursos"):
            st.dataframe(
                ul[["Nombre de la LE", "usuarios_cur", "usuarios_prev", "delta_usuarios",
                    "horas_cur", "horas_prev"]]
                .rename(columns={"usuarios_cur": "Usuarios (actual)",
                                 "usuarios_prev": "Usuarios (anterior)",
                                 "delta_usuarios": "Δ usuarios",
                                 "horas_cur": "Horas (actual)", "horas_prev": "Horas (anterior)"})
                .round(1),
                use_container_width=True, hide_index=True)


# ==================================================================
# PUENTE Y CALLEJÓN (lift de retención por curso)
# ==================================================================
elif seccion == "Puente y callejón":
    encabezado("panel histórico de snapshots usuario×LE", periodo=PERIODOS_PANEL)
    glosario(
        "Retención de los consumidores de cada curso contra la retención base de la plataforma.",
        "Para cada curso: **retención observada** = % de sus consumidores de un periodo que "
        "tienen más de 0 h (en cualquier curso) el periodo siguiente, agrupando todas las "
        "transiciones del panel. **Retención esperada** = tasa base de retorno de la plataforma "
        "en la misma selección. **Lift (pp)** = observada − esperada. Solo cursos con 100 "
        "transiciones-usuario o más.",
        {"Lift (pp)": "puntos porcentuales por encima (+) o por debajo (−) de la base.",
         "Base esperada": f"tasa de retorno periodo a periodo de la plataforma "
                          f"({R['base_ret']:.1f}% en esta selección).",
         "Curso puente": "lift positivo: sus consumidores vuelven por encima de la base.",
         "Curso callejón": "lift negativo: sus consumidores vuelven por debajo de la base.",
         "Transición-usuario": "un usuario con consumo en el curso en un periodo, observado "
                               "en el periodo siguiente.",
         "Periodos del panel": f"{EJES}."})

    lift = R["lift_estrategico"]
    if lift.empty:
        st.info("No hay cursos con 100 transiciones o más en esta selección.")
    else:
        c_m, c_sel, _ = st.columns([1, 1, 2])
        c_m.metric("Base esperada de retorno", f"{R['base_ret']:.1f}%")
        with c_sel:
            n = st.selectbox("Cursos por lado", [5, 8, 10, 15], index=1, key="n_lift")
        top_g = lift[lift["lift_pp"] > 0].head(n).iloc[::-1]
        top_c = lift[lift["lift_pp"] < 0].tail(n)
        # Ambos paneles comparten escala: si no, barras del mismo largo
        # representan magnitudes distintas.
        lim = float(np.nanmax(np.abs(np.concatenate(
            [top_g["lift_pp"].values, top_c["lift_pp"].values, [1.0]])))) * 1.35

        def _hover(df):
            return list(zip(df["retencion_obs_pct"], df["n_usuario_transiciones"],
                            df["Nombre de la LE"]))

        _ht = ("%{customdata[2]}<br>Lift %{x:+.1f} pp<br>Retención observada "
               "%{customdata[0]:.0f}%<br>Transiciones n=%{customdata[1]:,.0f}<extra></extra>")
        c1, c2 = st.columns(2)
        figg = go.Figure(go.Bar(
            x=top_g["lift_pp"], y=[corto(s) for s in top_g["Nombre de la LE"]],
            orientation="h", marker_color=VERDE,
            text=[f"{v:+.1f} pp" for v in top_g["lift_pp"]], textposition="outside",
            customdata=_hover(top_g), hovertemplate=_ht))
        figg.update_layout(title="Puente: lift positivo", xaxis_title="Lift (pp)",
                           xaxis_range=[0, lim])
        with c1:
            show(figg, height=460)
        figc = go.Figure(go.Bar(
            x=top_c["lift_pp"], y=[corto(s) for s in top_c["Nombre de la LE"]],
            orientation="h", marker_color=ROJO,
            text=[f"{v:+.1f} pp" for v in top_c["lift_pp"]], textposition="outside",
            customdata=_hover(top_c), hovertemplate=_ht))
        figc.update_layout(title="Callejón: lift negativo", xaxis_title="Lift (pp)",
                           xaxis_range=[-lim, 0])
        with c2:
            show(figc, height=460)

        with st.expander("Ver ranking completo"):
            st.dataframe(lift.drop(columns=["ID de la LE"]), use_container_width=True,
                         hide_index=True)


# ==================================================================
# ACTIVACIÓN: embudo de usuarios únicos
# ==================================================================
elif seccion == "Activación":
    encabezado("roster de licencias + snapshot usuario×LE")
    emb, embp = R["embudo"], R["embudo_prev"]
    glosario(
        "Usuarios únicos en cada escalón, desde tener licencia hasta acumular 5 h de consumo, "
        "y el mismo embudo en el periodo anterior.",
        "Todos los escalones son **usuarios únicos**. El primero sale del roster "
        "(`Listado_de_usuarios`, acumulado de vida); los demás del snapshot usuario×LE del "
        "periodo, sumando horas por usuario y contando cuántos alcanzan cada umbral. "
        "% de la base = usuarios del escalón / usuarios con licencia.",
        {"Licencia": "usuario que aparece en el roster del proveedor, tenga o no actividad.",
         "Inscrito": "tiene al menos una fila usuario×LE en el periodo, aunque con 0 h.",
         "Efectivo": "acumula más de 0 h en el periodo.",
         "20 min / 1 h / 5 h": "acumula al menos ese tiempo en el periodo, sumando todos "
                               "sus cursos.",
         "Roster": "mismo denominador en los dos periodos (acumulado de vida)."})

    fig = go.Figure(go.Bar(
        x=emb["usuarios"], y=emb["etapa"], orientation="h", marker_color=AZUL,
        text=[f"{u:,.0f}  ({p:.1f}% de la base)" for u, p in zip(emb["usuarios"], emb["pct_base"])],
        textposition="outside",
        customdata=list(zip(emb["pct_paso"], emb["fuente"])),
        hovertemplate="%{y}<br>%{x:,.0f} usuarios<br>% del escalón anterior: "
                      "%{customdata[0]:.1f}%<br>Fuente: %{customdata[1]}<extra></extra>"))
    fig.update_layout(title="Usuarios únicos por escalón, periodo actual",
                      xaxis_title="Usuarios", xaxis_range=[0, float(emb["usuarios"].max()) * 1.35],
                      yaxis=dict(autorange="reversed"))
    show(fig, height=420)

    _m = embp.set_index("etapa")["usuarios"]
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(name="Anterior", x=emb["etapa"], y=[_m.get(e, np.nan) for e in emb["etapa"]],
                          marker_color=GRIS_PREV))
    fig2.add_trace(go.Bar(name="Actual", x=emb["etapa"], y=emb["usuarios"], marker_color=AZUL))
    fig2.update_layout(barmode="group", title="Periodo actual contra anterior",
                       yaxis_title="Usuarios únicos", bargap=0.3)
    fig2.update_yaxes(rangemode="tozero")
    show(fig2, height=380)
    with st.expander("Ver tabla"):
        _t = emb[["etapa", "usuarios", "pct_base", "pct_paso"]].copy()
        _t["usuarios_anterior"] = [_m.get(e, np.nan) for e in _t["etapa"]]
        st.dataframe(_t.round(1), use_container_width=True, hide_index=True)
