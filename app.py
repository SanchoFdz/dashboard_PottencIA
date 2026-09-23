"""
Dashboard PottencIA / ODILO: versión interactiva del deck mensual del comité.

Reemplaza las presentaciones fijas (Datos PottencIA - <fecha>.pptx). Se actualiza
solo con reemplazar los CSV que Santiago descarga del proveedor Odilo BI en las
carpetas mnt/data/current, mnt/data/previous y datos_analisis_estrategico_2026.

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
    """Verde si mejora, rojo si empeora. Unico uso legitimo de verde/rojo."""
    return VERDE if v > 0 else (ROJO if v < 0 else GRIS)


# ---- Estilo unificado: fondo BLANCO + rejilla tenue (arregla el "fondo gris") ----
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
    """Bloque de contexto que acompaña a cada gráfica."""
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


def mom_pct(cur, prev):
    """Variacion % contra el periodo anterior, tolerante a ceros."""
    if prev in (0, None) or pd.isna(prev):
        return float("nan")
    return (cur - prev) / prev * 100.0


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
@st.cache_data(show_spinner="Cargando y limpiando los CSV del proveedor…", max_entries=1)
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
# esta vista es CEO-facing y la actualizacion de datos es tarea del equipo, no
# del lector. Para refrescar: reiniciar la app tras reemplazar los CSV.
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

st.sidebar.markdown(f"**Periodo actual:** {meta['cur_label']}")
st.sidebar.markdown(f"**Periodo anterior:** {meta['prev_label']}")
st.sidebar.caption(f"Generado {meta['generado']}")

# ==================================================================
# Navegación y filtro (barra superior, no sidebar)
# ==================================================================
# Con 16 secciones en una sola fila la barra se volvia ilegible, asi que la
# navegacion es de dos niveles. Los grupos agrupan por el objeto que miden:
# el periodo, las personas y el contenido.
GRUPOS = {
    "Periodo": ["Resumen", "Panorama", "Certificación", "Pulso"],
    "Usuarios": ["Activación", "Profundidad", "Abandono", "Retención",
                 "Crecimiento", "Tendencias", "Centro y Nivel"],
    "Contenido": ["Cursos", "Catálogo", "Formato", "Ruta Máster", "Lift"],
}
SECCIONES = [s for v in GRUPOS.values() for s in v]
TITULOS = {
    "Resumen": "Tres KPIs de cabecera",
    "Panorama": "Panorama del periodo",
    "Certificación": "Certificados obtenidos",
    "Pulso": "El pulso de la plataforma",
    "Activación": "Activación: de la licencia al consumo real",
    "Profundidad": "Profundidad de uso: cuánto consume quien consume",
    "Abandono": "Avance y abandono en las experiencias",
    "Retención": "Retención por cohorte",
    "Crecimiento": "Crecimiento de la base de usuarios",
    "Tendencias": "Tendencias diarias del periodo actual",
    "Centro y Nivel": "Centro y nivel educativo",
    "Cursos": "Cursos (Learning Experiences)",
    "Catálogo": "Catálogo: uso contra fecha de creación",
    "Formato": "Formato de curso (plantilla)",
    "Ruta Máster": "Ruta de Máster en IA (18 cursos)",
    "Lift": "Lift de retención por curso",
}

if "grupo_activo" not in st.session_state:
    st.session_state.grupo_activo = "Periodo"
grupo = st.segmented_control("Grupo", list(GRUPOS), default=st.session_state.grupo_activo,
                             label_visibility="collapsed", key="nav_grupo")
if grupo is None:
    grupo = st.session_state.grupo_activo
st.session_state.grupo_activo = grupo

seccion = st.segmented_control("Sección", GRUPOS[grupo], default=GRUPOS[grupo][0],
                               label_visibility="collapsed", key=f"nav_{grupo}")
if seccion is None:
    seccion = GRUPOS[grupo][0]

TODAS = "Todas"

# Secciones SIN dimension de marca: sus datos vienen de la serie diaria de
# plataforma, que el proveedor no desglosa por universidad (ver `computar` en
# pipeline.py: panorama, tendencias y serie_larga se calculan sobre `d`, no
# sobre los frames filtrados). Poner el filtro aqui no cambiaba ni un numero, y
# en Panorama era peor que inutil: los 4 KPIs seguian siendo globales pero el
# filtro activo hacia parecer que eran de la marca elegida.
SIN_MARCA = {
    "Tendencias": "La serie diaria de plataforma no trae desglose por universidad.",
    "Pulso": "La serie diaria larga no trae desglose por universidad.",
}

# La seleccion se guarda aparte del widget: al ocultarlo en una seccion global,
# Streamlit descarta el estado de su key y se perderia al volver.
if "marca_activa" not in st.session_state:
    st.session_state.marca_activa = TODAS

if seccion in SIN_MARCA:
    marca_sel = TODAS
    st.caption(f"Sin filtro por marca en esta sección. {SIN_MARCA[seccion]}")
else:
    marca_sel = st.segmented_control(
        "Marca", [TODAS] + BASE["marcas"], default=st.session_state.marca_activa,
        label_visibility="collapsed", key=f"marca_{seccion}",
        help="Tendencias y pulso no lo tienen porque su fuente, la serie diaria de "
             "plataforma, no trae desglose por universidad.")
    if marca_sel is None:
        marca_sel = TODAS
    st.session_state.marca_activa = marca_sel

es_global = marca_sel == TODAS
marcas_sel = BASE["marcas"] if es_global else [marca_sel]
marcas_key = None if es_global else (marca_sel,)

R = compute(st.session_state.reload_token, marcas_key)

etiqueta_marca = "todas las marcas" if es_global else marca_sel
st.divider()


# ==================================================================
# ① PANORAMA
# ==================================================================
if seccion == "Panorama":
    st.header(TITULOS[seccion])

    # Los KPIs cambian de FUENTE segun el filtro, porque la serie diaria de
    # plataforma no trae desglose por universidad:
    #   - Todas  -> serie diaria de plataforma (4 KPIs, incluye efectivos).
    #   - 1 marca -> snapshot usuario x LE de esa marca (3 KPIs).
    # Nunca se mezclan en la misma fila: los universos son distintos (la serie
    # diaria mide ~3x las horas del snapshot). Ver la nota de medición del README.
    if es_global:
        pan = R["panorama"]
        st.caption(f"{meta['cur_label']} vs {meta['prev_label']} · fuente: serie diaria "
                   f"de plataforma · todas las marcas")
    else:
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
        st.caption(f"{meta['cur_label']} vs {meta['prev_label']} · fuente: snapshot "
                   f"usuario×LE · {marca_sel}")

    if es_global:
        glosario(
            "Los 4 KPIs de cabecera del periodo y su variación contra el periodo anterior.",
            "Suma de la **serie diaria de plataforma** del periodo. Δ% = (actual − anterior) / anterior. "
            "Usuarios efectivos se divide entre 2 (corrección de doble conteo heredada del deck).",
            {"Usuarios activos": "cualquier interacción registrada en el periodo.",
             "Usuarios efectivos": "usuarios con consumo real (métrica más estricta del portal).",
             "Contenidos únicos": "recursos distintos consumidos (DISTINCT_COUNT)."})
    else:
        glosario(
            f"Los KPIs de {marca_sel} y su variación contra el periodo anterior.",
            "Suma del **snapshot usuario×LE** de la marca. Δ% = (actual − anterior) / anterior. "
            "Al filtrar por universidad la fuente cambia, porque la serie diaria de "
            "plataforma no trae desglose por marca. Por eso estos valores no son "
            "comparables con los de «Todas»: miden universos distintos.",
            {"Horas consumidas": "suma de horas de la marca en el periodo.",
             "Contenidos consumidos": "suma de contenidos consumidos por la marca.",
             "Usuarios con consumo": "usuarios distintos de la marca con al menos un registro."})

    cols = st.columns(len(pan))
    for col, (_, r) in zip(cols, pan.iterrows()):
        col.metric(r["kpi"], fmt(r["actual"]), delta_txt(r["delta_pct"]))

    # Los cuatro KPIs tienen unidades incomparables (horas, contenidos, personas),
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
    st.caption("Un panel por métrica: dentro de cada uno las universidades comparten eje "
               "y arrancan en cero, así que los largos de barra sí son comparables.")
    pm = R["panorama_marca"]

    if not es_global:
        st.caption(f"La comparación mantiene las cuatro marcas: **{marca_sel}** va "
                   f"resaltada. Con una sola barra no habría nada que comparar.")
    _op = [1.0 if (es_global or u == marca_sel) else 0.35 for u in pm["Universidad"]]

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
# ② TENDENCIAS DIARIAS
# ==================================================================
elif seccion == "Tendencias":
    st.header(TITULOS[seccion])
    st.caption("Fuente: serie diaria de plataforma (global, sin desglose por marca)")
    glosario(
        "El ritmo día a día del periodo actual comparado con el promedio diario del anterior.",
        "Línea = media móvil de 7 días de la serie diaria. Línea gris punteada = promedio "
        "diario del periodo anterior.",
        {"Rolling 7d": "suaviza el ruido diario promediando cada día con los 6 previos.",
         "Promedio periodo ant.": "promedio diario del periodo anterior, como referencia fija."})
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
    # Media y mediana del dia: si difieren mucho, el periodo trae picos que la
    # media esconde (cargas masivas, campannas, cierres de asignatura).
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
# ③ SEGMENTACIÓN
# ==================================================================
elif seccion == "Profundidad":
    st.header(TITULOS[seccion])
    st.caption(f"Fuente: snapshot usuario×LE del periodo actual · {etiqueta_marca}")
    glosario(
        "Cómo se reparten los usuarios entre no activados y los 4 niveles de intensidad.",
        "Se suman las horas por usuario en el mes y se clasifican por umbrales fijos de horas.",
        {"No activados": "0 horas en el mes.",
         "Exploradores": "0–1 h.", "Constantes": "1–5 h.",
         "Intensivos": "5–20 h.", "Power users": ">20 h."})
    seg = R["segmentacion_global"]
    act, inten = seg["activacion"], seg["intensidad"]
    dc, dp = R["dist_cur"], R["dist_prev"]

    # Media Y mediana, siempre juntas: con esta distribucion la media describe
    # al top 5% (que concentra la mitad de las horas) y la mediana al alumno.
    st.subheader("Horas por alumno: media contra mediana")
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
    st.caption(f"La media ({dc['media_act']*60:.0f} min) es "
               f"{dc['media_act']/dc['mediana_act']:.1f} veces la mediana "
               f"({dc['mediana_act']*60:.0f} min)."
               if dc["mediana_act"] else "")
    st.divider()
    _noact = float(act.get("No activados", float("nan")))

    c1, c2 = st.columns([1, 1.6])
    with c1:
        st.metric("Usuarios activados", f"{(1-_noact)*100:.1f}%")
        st.caption(f"El {_noact*100:.1f}% restante no registró ni una hora en el periodo.")
        # Una barra apilada lee mejor que una dona: la dona rotaba la etiqueta
        # de "No activados" 90 grados y quedaba ilegible.
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
        # Dispersion entre marcas: el dato que resume las cuatro barras apiladas.
        disp = (sm["Exploradores"].max() - sm["Exploradores"].min()) * 100
        _alta = sm.loc[sm["Exploradores"].idxmax(), "Universidad"]
        _baja = sm.loc[sm["Exploradores"].idxmin(), "Universidad"]
        st.caption(f"% de exploradores: {sm['Exploradores'].max()*100:.1f}% en {_alta} y "
                   f"{sm['Exploradores'].min()*100:.1f}% en {_baja} ({disp:.1f} puntos "
                   f"de diferencia).")
        if not es_global:
            st.caption(f"La comparación mantiene las cuatro marcas: **{marca_sel}** va "
                       f"resaltada. Con una sola barra no habría nada que comparar.")
        fig3 = go.Figure()
        for s in pl.SEG_ORDER:
            # Cuando hay marca elegida, las demas bajan de opacidad en vez de
            # desaparecer: el contexto de comparacion es el valor de la grafica.
            op = [1.0 if (es_global or u == marca_sel) else 0.35
                  for u in sm["Universidad"]]
            fig3.add_trace(go.Bar(name=s, x=sm["Universidad"], y=sm[s] * 100,
                                  marker=dict(color=SEG_COLORS[s], opacity=op)))
        fig3.update_layout(barmode="stack", yaxis_title="% de activados", bargap=0.45)
        show(fig3, height=300)
        with st.expander("Ver tabla (incluye % No activados)"):
            st.dataframe(sm, use_container_width=True, hide_index=True)


# ==================================================================
# ④ ABANDONO
# ==================================================================
elif seccion == "Abandono":
    st.header(TITULOS[seccion])
    st.caption(f"Fuente: snapshot usuario×LE · {etiqueta_marca}")
    glosario(
        "Hasta dónde llega la gente en los cursos: se quedan al inicio o los terminan.",
        "Para cada par (usuario, curso) se toma su **máximo tramo** de avance y se cuenta "
        "cuántos pares caen en cada rango. Se compara la distribución del periodo actual vs. anterior.",
        {"Par (usuario, curso)": "una inscripción concreta de una persona a un curso.",
         "Tramo": "banda de avance reportada por el portal (0–20, 20–50, 50–80, 80–100%).",
         "Abandono temprano": "% de pares que no pasan del 20%."})
    ab, abp = R["abandono_cur"], R["abandono_prev"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Se quedan bajo 20%", f"{ab['pct_bajo20']*100:.1f}%",
              f"{(ab['pct_bajo20']-abp['pct_bajo20'])*100:+.1f} pp vs periodo ant.",
              delta_color="inverse")
    c2.metric("Llegan a ≥80%", f"{ab['pct_alto80']*100:.1f}%",
              f"{(ab['pct_alto80']-abp['pct_alto80'])*100:+.1f} pp vs periodo ant.")
    c3.metric("Pares (usuario, curso)", fmt(len(ab["detalle"])))

    tramos_lbl = {10: "0–20%", 35: "20–50%", 65: "50–80%", 90: "80–100%"}
    dc, dp = ab["dist_tramos"], abp["dist_tramos"]
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Actual", x=[tramos_lbl.get(i, i) for i in dc.index],
                         y=dc.values * 100, marker_color=AZUL,
                         text=[f"{v*100:.0f}%" for v in dc.values], textposition="outside"))
    fig.add_trace(go.Bar(name="Anterior", x=[tramos_lbl.get(i, i) for i in dp.index],
                         y=dp.values * 100, marker_color=GRIS_PREV))
    fig.update_layout(barmode="group", yaxis_title="% de pares",
                      xaxis_title="Tramo de avance máximo")
    show(fig, height=430)


# ==================================================================
# ⑤ CURSOS (LEs)
# ==================================================================
elif seccion == "Cursos":
    st.header(TITULOS[seccion])
    st.caption(f"Fuente: snapshot usuario×LE · {etiqueta_marca}")
    glosario(
        "Qué cursos concentran las horas y cuáles suben o bajan respecto al periodo anterior.",
        "Suma de horas por curso en el periodo actual (Top 5) y diferencia de horas vs. el "
        "periodo anterior (Δ). Solo entran en Δ los cursos con ≥1 h el periodo anterior.",
        {"LE": "Learning Experience = un curso/club del catálogo (~83–120 LEs).",
         "Δ horas": "horas de este periodo menos las del periodo anterior."})
    tl = R["top_les"]

    st.subheader("Top 5 por horas consumidas (periodo actual)")
    th = tl["top_horas"].iloc[::-1]
    fig = go.Figure(go.Bar(x=th["horas_cur"], y=[corto(s) for s in th["Nombre de la LE"]],
                           orientation="h",
                           marker_color=AZUL, text=[fmt(v) for v in th["horas_cur"]],
                           textposition="auto"))
    fig.update_layout(xaxis_title="Horas")
    show(fig, height=380)

    c1, c2 = st.columns(2)
    tm = tl["top_mejora"].iloc[::-1]
    # Invertido igual que tm para que la mayor caida quede ARRIBA en los dos
    # paneles; sin esto el orden vertical era opuesto entre subidas y caidas.
    bc = tl["bottom_caida"].iloc[::-1]
    figm = go.Figure(go.Bar(x=tm["delta"], y=[corto(s) for s in tm["Nombre de la LE"]],
                            orientation="h",
                            marker_color=VERDE, text=[f"{v:+.0f}" for v in tm["delta"]],
                            textposition="auto"))
    # Escala compartida entre los dos paneles: con ejes independientes una
    # caida de 122 h y una subida de 30 h se dibujaban del mismo largo.
    _lim = float(np.nanmax(np.abs(np.concatenate(
        [tm["delta"].values, bc["delta"].values])))) * 1.35 if not bc.empty else None
    figm.update_layout(title="Top 5 que más crecieron (Δ horas)",
                       xaxis_range=[0, _lim] if _lim else None,
                       xaxis_title="Δ horas vs periodo anterior")
    with c1:
        show(figm, height=360)
    figc = go.Figure(go.Bar(x=bc["delta"], y=[corto(s) for s in bc["Nombre de la LE"]],
                            orientation="h",
                            marker_color=ROJO, text=[f"{v:+.0f}" for v in bc["delta"]],
                            textposition="auto"))
    figc.update_layout(title="Top 5 que más cayeron (Δ horas)",
                       xaxis_range=[-_lim, 0] if _lim else None,
                       xaxis_title="Δ horas vs periodo anterior")
    with c2:
        show(figc, height=360)


# ==================================================================
# ⑥ SERIE LARGA
# ==================================================================
elif seccion == "Pulso":
    st.header(TITULOS[seccion])
    st.caption("Serie diaria de horas (global) · rolling 7d, tendencia 28d e índice estacional")
    _s = R["serie_larga"].dropna(subset=["r7"])
    if len(_s) > 60:
        _pico = _s.loc[_s["r7"].idxmax()]
        _hoy = float(_s["r7"].iloc[-1])
        _caida = (_hoy / float(_pico["r7"]) - 1) * 100
        st.caption(f"Máximo de la serie: {_pico['fecha']:%d-%b-%Y} con {_pico['r7']:,.0f} h/día. "
                   f"Último valor: {_hoy:,.0f} h/día ({_caida:+.0f}% vs el máximo).")
    glosario(
        "La serie diaria de horas desde Dic-2025, anotada con los eventos conocidos.",
        "Panel superior: media móvil de 7 días (azul) y tendencia de 28 días (gris). "
        "Panel inferior: índice = horas del día / tendencia 28d (>1 = por encima de su propia tendencia).",
        {"Tendencia 28d": "media móvil centrada de 4 semanas; el nivel 'normal' del momento.",
         "Índice estacional": "aísla los picos/valles de gestión de la estacionalidad del calendario.",
         "Carga masiva": "alta masiva de usuarios (Feb-2026), anotada en la serie."})
    s = R["serie_larga"]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.65, 0.35],
                        subplot_titles=["Horas de aprendizaje / día",
                                        "Índice vs tendencia local (>1 = sobre su propia tendencia)"])
    fig.add_trace(go.Scatter(x=s["fecha"], y=s["r7"], line=dict(color=AZUL, width=2),
                             name="Horas/día (7d)"), row=1, col=1)
    fig.add_trace(go.Scatter(x=s["fecha"], y=s["r28"], line=dict(color=GRIS, width=1.5, dash="dash"),
                             name="Tendencia 28d"), row=1, col=1)
    fig.add_trace(go.Scatter(x=s["fecha"], y=s["idx_estacional"], line=dict(color="#CFC3E4", width=0.5),
                             fill="tozeroy", name="Índice", showlegend=False), row=2, col=1)
    fig.add_hline(y=1, line=dict(color=GRIS, dash="dash"), row=2, col=1)
    for f, txt in [("2026-02-01", "Carga masiva")]:
        fdt = pd.to_datetime(f)
        if s["fecha"].min() <= fdt <= s["fecha"].max():
            fig.add_shape(type="line", x0=fdt, x1=fdt, yref="y domain", y0=0, y1=1,
                          line=dict(color=ROJO, width=1, dash="dot"), row=1, col=1)
            fig.add_annotation(x=fdt, yref="y domain", y=1, text=txt, textangle=-90,
                               showarrow=False, font=dict(size=9, color=ROJO),
                               xanchor="left", yanchor="top", row=1, col=1)
    show(fig, height=600)


# ==================================================================
# ⑦ GROWTH ACCOUNTING
# ==================================================================
elif seccion == "Crecimiento":
    st.header(TITULOS[seccion])
    st.caption(f"Composición de los usuarios activos de cada mes · {etiqueta_marca}")
    _ga = R["growth"]
    if len(_ga) >= 2:
        _u = _ga.iloc[-1]
        _pct_rec = _u["Recurrentes"] / _u["Total activos"] * 100 if _u["Total activos"] else float("nan")
        _neto = _u["Nuevos"] + _u["Reactivados"] - _u["Perdidos"]
        st.caption(f"{_u['eje']}: {_pct_rec:.0f}% de los activos son recurrentes · "
                   f"{_u['Nuevos']:,.0f} nuevos · {_u['Perdidos']:,.0f} perdidos · "
                   f"saldo neto {_neto:+,.0f}.")
    glosario(
        "De qué está hecha la base activa de cada mes: gente nueva, que repite, que vuelve o que se pierde.",
        "Para cada mes se clasifica a cada usuario activo según su historial: nuevo (primera vez), "
        "recurrente (activo el mes pasado), reactivado (activo antes pero no el mes pasado). "
        "Perdidos = activos el mes pasado que no lo están este mes.",
        {"Nuevos": "se activan por primera vez.",
         "Recurrentes": "activos dos meses seguidos.",
         "Reactivados": "vuelven tras una pausa.",
         "Perdidos": "estaban activos y dejaron de estarlo (línea roja)."})
    ga = R["growth"]

    fig = go.Figure()
    for col, color in [("Recurrentes", "#5B0FA8"), ("Reactivados", "#9B4FD1"), ("Nuevos", "#D9C2F2")]:
        fig.add_trace(go.Bar(name=col, x=ga["eje"], y=ga[col], marker_color=color))
    fig.add_trace(go.Scatter(name="Perdidos", x=ga["eje"], y=-ga["Perdidos"],
                             line=dict(color=ROJO, width=2), mode="lines+markers"))
    fig.update_layout(barmode="stack", yaxis_title="Usuarios activos")
    show(fig, height=460)

    ga2 = ga.copy()
    ga2["% recurrentes"] = (ga2["Recurrentes"] / ga2["Total activos"] * 100).round(0)
    st.dataframe(ga2[["eje", "Nuevos", "Recurrentes", "Reactivados", "Total activos",
                      "Perdidos", "% recurrentes"]], use_container_width=True, hide_index=True)

    st.subheader("Por marca")
    gm = R["growth_marca"]
    if not es_global:
        st.caption(f"La comparación mantiene las cuatro marcas; **{marca_sel}** va marcada "
                   f"con «▸». Los paneles de arriba sí responden al filtro.")
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
# ⑧ COHORTES
# ==================================================================
elif seccion == "Retención":
    st.header(TITULOS[seccion])
    st.caption(f"% de cada cohorte que sigue activo N periodos después · {etiqueta_marca}")
    _coh = R["cohortes"]
    if "m1" in _coh.columns and _coh["m1"].notna().any():
        _m1 = _coh["m1"].dropna()
        st.caption(f"Retorno en +1 periodo: media {_m1.mean()*100:.0f}% de la cohorte, "
                   f"mínimo {_m1.min()*100:.0f}%, máximo {_m1.max()*100:.0f}%.")
    glosario(
        "Cuánto aguanta cada 'generación' de usuarios según el mes en que se activó por primera vez.",
        "Se agrupa a los usuarios por su mes de primera actividad (cohorte) y se mide qué "
        "porcentaje sigue activo 1, 2, 3… periodos después. m0 siempre es 100%.",
        {"Cohorte": "todos los que se activaron por primera vez el mismo mes.",
         "+N": "N periodos después de la primera actividad."})
    coh = R["cohortes"]
    mcols = [c for c in coh.columns if c.startswith("m")]

    z = coh[mcols].values.astype(float) * 100
    fig = go.Figure(go.Heatmap(
        z=z, x=[f"+{i}" for i in range(len(mcols))],
        y=[f"{r.Cohorte} (n={int(r.n):,})" for r in coh.itertuples()],
        colorscale=ESCALA_MARCA, zmin=0, zmax=float(np.nanmax(z[:, 1:])) if z.shape[1] > 1 else 100,
        text=[[f"{v:.0f}" if not np.isnan(v) else "" for v in row] for row in z],
        texttemplate="%{text}", colorbar=dict(title="%")))
    fig.update_layout(yaxis=dict(autorange="reversed"),
                      xaxis_title="Periodos desde la primera actividad")
    show(fig, height=430)

    figc = go.Figure()
    # Azules de claro (cohorte vieja) a oscuro (reciente): la secuencia se lee
    # como orden temporal, algo que los colores por defecto no comunican.
    _tot = max(len(coh), 2)
    for i, r in enumerate(coh.itertuples()):
        ys = [getattr(r, c) * 100 if not pd.isna(getattr(r, c)) else None for c in mcols]
        # Rampa de marca: lila claro (cohorte vieja) a violeta profundo (reciente).
        _mix = 0.18 + 0.82 * (i / (_tot - 1))
        _col = f"rgb({int(233 - 142*_mix)},{int(223 - 208*_mix)},{int(250 - 82*_mix)})"
        figc.add_trace(go.Scatter(x=list(range(len(mcols))), y=ys, mode="lines+markers",
                                  line=dict(color=_col, width=2),
                                  marker=dict(color=_col, size=6), name=r.Cohorte))
    figc.update_layout(title="Curvas de vida", yaxis_title="% de la cohorte activo",
                       xaxis_title="Periodos desde la primera actividad")
    show(figc, height=420)


# ==================================================================
# ⑨ LIFT DE RETENCIÓN (métrica del análisis estratégico)
# ==================================================================
elif seccion == "Lift":
    st.header(TITULOS[seccion])
    st.caption(f"Métrica del análisis estratégico (observada vs. esperada) · {etiqueta_marca}")
    glosario(
        "Retención de cada curso contra la base global: por encima (gancho) o por debajo (callejón).",
        "Para cada curso: **retención observada** = % de sus consumidores de un mes que siguen "
        "activos (en cualquier curso) el mes siguiente, agrupando todos los meses. "
        "**Retención esperada** = tasa base global de retorno de la plataforma. "
        "**Lift (pp)** = observada − esperada. Solo cursos con ≥100 transiciones-usuario.",
        {"Lift (pp)": "puntos porcentuales por encima/debajo de la base. +10 pp = retiene 10 puntos más que el promedio.",
         "Base esperada": f"tasa global de retorno mes→mes ({R['base_ret']:.1f}% en esta selección).",
         "Gancho": "lift positivo: sus consumidores vuelven por encima de la base.",
         "Callejón": "lift negativo: sus consumidores vuelven por debajo de la base.",
         "Gateway": "curso con el que ARRANCAN los usuarios nuevos, y cuánto retiene."})

    lift = R["lift_estrategico"]
    if lift.empty:
        st.info("No hay suficientes datos (≥100 transiciones por curso) en esta selección.")
    else:
        st.metric("Base esperada de retorno (esta selección)", f"{R['base_ret']:.1f}%")
        _c_sel, _ = st.columns([1, 2])
        with _c_sel:
            n = st.selectbox("Cursos por lado", [5, 8, 10, 15], index=1)
        top_g = lift.head(n).iloc[::-1]
        top_c = lift.tail(n)
        c1, c2 = st.columns(2)
        figg = go.Figure(go.Bar(
            x=top_g["lift_pp"], y=[corto(s) for s in top_g["Nombre de la LE"]],
            orientation="h", marker_color=VERDE,
            text=[f"{v:+.1f} pp" for v in top_g["lift_pp"]], textposition="outside",
            customdata=list(zip(top_g["retencion_obs_pct"], top_g["n_usuario_transiciones"],
                                top_g["Nombre de la LE"])),
            hovertemplate="%{customdata[2]}<br>Lift %{x:+.1f} pp<br>"
                          "Retencion observada %{customdata[0]:.0f}%<br>"
                          "Transiciones n=%{customdata[1]:,.0f}<extra></extra>"))
        # Ambos paneles comparten escala: si no, barras del mismo largo
        # representan magnitudes distintas y la comparacion visual enganna.
        lim = float(np.nanmax(np.abs(np.concatenate(
            [top_g["lift_pp"].values, top_c["lift_pp"].values])))) * 1.35
        figg.update_layout(title="Gancho: retienen por encima de la base",
                           xaxis_title="Lift (pp)", xaxis_range=[0, lim])
        with c1:
            show(figg, height=460)
        figc = go.Figure(go.Bar(
            x=top_c["lift_pp"], y=[corto(s) for s in top_c["Nombre de la LE"]],
            orientation="h", marker_color=ROJO,
            text=[f"{v:+.1f} pp" for v in top_c["lift_pp"]], textposition="inside",
            insidetextfont=dict(color="white"), textangle=0,
            customdata=list(zip(top_c["retencion_obs_pct"], top_c["n_usuario_transiciones"],
                                top_c["Nombre de la LE"])),
            hovertemplate="%{customdata[2]}<br>Lift %{x:+.1f} pp<br>"
                          "Retencion observada %{customdata[0]:.0f}%<br>"
                          "Transiciones n=%{customdata[1]:,.0f}<extra></extra>"))
        figc.update_layout(title="Callejón: por debajo de la base",
                           xaxis_title="Lift (pp)", xaxis_range=[-lim, 0])
        with c2:
            show(figc, height=460)

        with st.expander("Ver ranking completo"):
            st.dataframe(lift, use_container_width=True, hide_index=True)

        # ---- Gateway de usuarios nuevos ----
        st.subheader("Puerta de entrada (gateway de usuarios nuevos)")
        st.caption("Con qué curso arrancan los usuarios NUEVOS y su lift de retención.")
        gw = R["gateway"]
        if not gw.empty:
            gtop = gw.head(n).iloc[::-1]
            figw = go.Figure(go.Bar(
                x=gtop["lift_pp"], y=[corto(s) for s in gtop["Nombre de la LE"]],
                orientation="h", marker_color=AZUL,
                text=[f"{v:+.1f} pp" for v in gtop["lift_pp"]], textposition="outside",
                customdata=list(zip(gtop["retencion_obs_pct"], gtop["n"],
                                    gtop["Nombre de la LE"])),
                hovertemplate="%{customdata[2]}<br>Lift %{x:+.1f} pp<br>"
                              "Retencion observada %{customdata[0]:.0f}%<br>"
                              "Usuarios nuevos n=%{customdata[1]:,.0f}<extra></extra>"))
            figw.update_layout(title="Mejores puertas de entrada (por lift)", xaxis_title="Lift (pp)")
            show(figw, height=440)
            with st.expander("Ver tabla de gateways"):
                st.dataframe(gw, use_container_width=True, hide_index=True)

    with st.expander("¿En qué se diferencia del lift del deck (s2d)?"):
        st.markdown(
            "El deck usaba una base **por mes** y promediaba los lifts. Esta versión "
            "(la del análisis estratégico) usa una **base global única** y agrupa todas las "
            "transiciones. Aquí tienes ambas para referencia:")
        if not R["lift_deck"].empty:
            st.dataframe(R["lift_deck"].round(2), use_container_width=True, hide_index=True)
# ==================================================================
# RESUMEN (portada): los tres KPIs que el comite quiere mover
# ==================================================================
elif seccion == "Resumen":
    st.header(TITULOS[seccion])
    st.caption(f"{meta['cur_label']} vs {meta['prev_label']} · {etiqueta_marca}")

    dc, dp = R["dist_cur"], R["dist_prev"]
    emb, embp = R["embudo"], R["embudo_prev"]

    def _etapa(df, nombre):
        f = df[df["etapa"] == nombre]
        return int(f["usuarios"].iloc[0]) if len(f) else None

    lic = _etapa(emb, "Usuarios con licencia")
    efe_cur = _etapa(emb, "Efectivos: consumo > 0 h")
    efe_prev = _etapa(embp, "Efectivos: consumo > 0 h")
    act_cur = (efe_cur / lic * 100) if lic else np.nan
    act_prev = (efe_prev / lic * 100) if lic else np.nan

    # Retencion: la cohorte mas antigua en su ultimo periodo observado. Es la
    # misma lectura que llevo el comite ("12% de los de enero siguen en agosto").
    coh = R["cohortes"]
    _mc = [c for c in coh.columns if c.startswith("m")]
    ret_pct = ret_n = ret_lbl = None
    if len(coh) and _mc:
        fila = coh.iloc[0]
        vivos = [c for c in _mc if pd.notna(fila.get(c))]
        if vivos:
            ult = vivos[-1]
            ret_pct = float(fila[ult]) * 100
            ret_n = int(round(float(fila[ult]) * float(fila["n"])))
            ret_lbl = f"cohorte {fila['Cohorte']} en +{ult[1:]}"

    c1, c2, c3 = st.columns(3)
    c1.metric("① Activación efectiva",
              f"{act_cur:.1f}%" if pd.notna(act_cur) else "s/d",
              delta_txt(act_cur - act_prev, sufijo=" pp vs periodo anterior")
              if pd.notna(act_cur) and pd.notna(act_prev) else None)
    c1.caption(f"{fmt(efe_cur)} usuarios con consumo > 0 h sobre {fmt(lic)} con licencia."
               if lic else "Sin roster de licencias.")
    c2.metric("② Tiempo de consumo (mediana)", f"{dc['mediana_act']*60:.0f} min",
              delta_txt((dc["mediana_act"] - dp["mediana_act"]) * 60,
                        sufijo=" min vs periodo anterior", dec=0))
    c2.caption(f"Media {dc['media_act']*60:.0f} min ({dc['media_act']/dc['mediana_act']:.1f}x "
               f"la mediana)." if dc["mediana_act"] else "")
    c3.metric("③ Retención", f"{ret_pct:.1f}%" if ret_pct is not None else "s/d")
    c3.caption(f"{fmt(ret_n)} de {fmt(float(coh.iloc[0]['n']))} alumnos ({ret_lbl})."
               if ret_pct is not None else "")

    glosario(
        "Los tres KPIs de cabecera, calculados con la data que ya existe.",
        "**① Activación** = usuarios con consumo > 0 h en el periodo / usuarios con licencia "
        "(roster acumulado). **② Tiempo de consumo** = mediana de horas por usuario activado, "
        "en minutos (se muestra también la media). "
        "**③ Retención** = % de la cohorte más antigua que sigue activa en su último periodo observado.",
        {"Denominador de activación": "usuarios con licencia del roster. La cifra de logins "
                                      "históricos que maneja el comité no viene en estas "
                                      "exportaciones.",
         "Media y mediana": "el top 5% de usuarios concentra el "
                            f"{dc['share_top5']:.0f}% de las horas, así que media y mediana "
                            "difieren mucho.",
         "Sin umbrales": "las tres tarjetas no llevan semáforo: no hay metas definidas en la data."})

    st.subheader("Dónde se detalla cada KPI")
    st.caption("Secciones del dashboard donde aparece el desglose de cada KPI.")
    st.dataframe(pd.DataFrame([
        {"KPI": "① Activación", "Hoy": f"{act_cur:.1f}%" if pd.notna(act_cur) else "s/d",
         "Secciones": "Activación, Centro y Nivel, Catálogo, Formato"},
        {"KPI": "② Tiempo de consumo", "Hoy": f"{dc['mediana_act']*60:.0f} min (mediana)",
         "Secciones": "Profundidad, Abandono, Formato, Ruta Máster, Cursos"},
        {"KPI": "③ Retención", "Hoy": f"{ret_pct:.1f}%" if ret_pct is not None else "s/d",
         "Secciones": "Retención, Crecimiento, Lift, Ruta Máster"},
    ]), use_container_width=True, hide_index=True)


# ==================================================================
# ACTIVACIÓN: embudo de usuarios únicos + activos vs efectivos
# ==================================================================
elif seccion == "Activación":
    st.header(TITULOS[seccion])
    st.caption(f"Usuarios únicos · roster de licencias + snapshot usuario×LE · {etiqueta_marca}")
    emb, embp = R["embudo"], R["embudo_prev"]
    glosario(
        "Cuánta gente hay en cada escalón, de tener licencia a consumir de verdad.",
        "Todos los escalones son **usuarios únicos**. El primero sale del roster "
        "(`Listado_de_usuarios`, acumulado de vida); los demás del snapshot usuario×LE del "
        "periodo, sumando horas por usuario y contando cuántos superan cada umbral.",
        {"Licencia": "usuario que aparece en el roster del proveedor, tenga o no actividad.",
         "Inscrito": "tiene al menos una fila usuario×LE en el periodo, aunque con 0 h.",
         "Efectivo": "acumula más de 0 h en el periodo.",
         "20 min": "umbral que el comité usa para hablar de tiempo de consumo (1/3 de hora).",
         "Activo (serie diaria)": "definición del portal: entró a la plataforma. No es una "
                                  "persona única, es un conteo por día (ver panel de abajo)."})

    fig = go.Figure(go.Bar(
        x=emb["usuarios"], y=emb["etapa"], orientation="h", marker_color=AZUL,
        text=[f"{u:,.0f}  ({p:.1f}% de la base)" for u, p in zip(emb["usuarios"], emb["pct_base"])],
        textposition="outside",
        customdata=list(zip(emb["pct_paso"], emb["fuente"])),
        hovertemplate="%{y}<br>%{x:,.0f} usuarios<br>Pasa del escalón anterior: "
                      "%{customdata[0]:.1f}%<br>Fuente: %{customdata[1]}<extra></extra>"))
    fig.update_layout(title="Embudo de usuarios únicos del periodo",
                      xaxis_title="Usuarios", xaxis_range=[0, float(emb["usuarios"].max()) * 1.35],
                      yaxis=dict(autorange="reversed"))
    show(fig, height=420)

    st.subheader("Contra el periodo anterior")
    st.caption("Mismo escalón, misma escala: el roster es el mismo en los dos periodos.")
    _m = embp.set_index("etapa")["usuarios"]
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(name="Anterior", x=emb["etapa"], y=[_m.get(e, np.nan) for e in emb["etapa"]],
                          marker_color=GRIS_PREV))
    fig2.add_trace(go.Bar(name="Actual", x=emb["etapa"], y=emb["usuarios"], marker_color=AZUL))
    fig2.update_layout(barmode="group", yaxis_title="Usuarios únicos", bargap=0.3)
    fig2.update_yaxes(rangemode="tozero")
    show(fig2, height=380)

    st.subheader("Activos vs efectivos (definición del portal)")
    ae = R["act_vs_efe"]["cur"]
    st.caption(f"Activo = entró a la plataforma. Efectivo = tuvo alguna actividad. "
               f"Son conteos por día sumados sobre {ae['dias']} días (usuario-día), "
               f"no personas distintas, así que no entran en el embudo de arriba.")
    k1, k2, k3 = st.columns(3)
    k1.metric("Activos por día (media)", fmt(ae["activos_dia_media"]),
              f"mediana {ae['activos_dia_mediana']:,.0f}", delta_color="off")
    k2.metric("Efectivos por día (media)", fmt(ae["efectivos_dia_media"]),
              f"mediana {ae['efectivos_dia_mediana']:,.0f}", delta_color="off")
    k3.metric("Efectivos / activos", f"{ae['ratio']:.1f}%")
    st.caption("El ratio se calcula sobre los valores crudos del portal: la corrección ÷2 que el "
               "deck aplica a los efectivos solo entra en el KPI de panorama.")


# ==================================================================
# CERTIFICACIÓN (resultado)
# ==================================================================
elif seccion == "Certificación":
    st.header(TITULOS[seccion])
    st.caption(f"Fuente: snapshot usuario×LE, columna Certificado · {etiqueta_marca}")
    cc, cp = R["cert_cur"], R["cert_prev"]
    st.caption(f"Certifican el {cc['tasa_cert_entre_fin']:.0f}% de los pares que llegan al "
               f"tramo 80-100%.")
    glosario(
        "Cuántos certificados se obtuvieron y qué parte de la base los consigue.",
        "`Certificado` es una columna del par (usuario, LE): dice si **ese alumno** obtuvo el "
        "certificado en **ese curso**. Se cuentan pares con `Si`, alumnos distintos con al menos "
        "uno, y la tasa entre los pares que llegan al tramo 80-100%.",
        {"Atributo del par, no del curso": "99 de 112 LEs tienen filas Si y No a la vez.",
         "Tasa por usuario": "alumnos con al menos un certificado / alumnos inscritos en el periodo.",
         "Certificados sin avance": f"{fmt(cc['incoherentes'])} pares traen certificado con avance "
                                    "declarado bajo 20%."})
    k = st.columns(4)
    k[0].metric("Certificados obtenidos", fmt(cc["certificados"]),
                delta_txt(mom_pct(cc["certificados"], cp["certificados"])))
    k[1].metric("Alumnos con certificado", fmt(cc["usuarios_con_cert"]),
                delta_txt(mom_pct(cc["usuarios_con_cert"], cp["usuarios_con_cert"])))
    k[2].metric("Tasa por alumno", f"{cc['tasa_usuario']:.1f}%",
                delta_txt(cc["tasa_usuario"] - cp["tasa_usuario"], sufijo=" pp vs periodo anterior"))
    k[3].metric("Certificados por alumno certificado",
                f"{cc['cert_por_usuario_media']:.1f}",
                f"mediana {cc['cert_por_usuario_mediana']:.0f}", delta_color="off")

    cpp = R["cert_periodo"]
    if not cpp.empty:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Bar(x=cpp["eje"], y=cpp["Certificados"], name="Certificados",
                             marker_color=AZUL), secondary_y=False)
        fig.add_trace(go.Scatter(x=cpp["eje"], y=cpp["Tasa por usuario (%)"], name="Tasa por alumno",
                                 mode="lines+markers", line=dict(color=GRIS, width=2)),
                      secondary_y=True)
        fig.update_yaxes(title_text="Certificados", rangemode="tozero", secondary_y=False)
        fig.update_yaxes(title_text="% de alumnos con certificado", rangemode="tozero",
                         secondary_y=True, showgrid=False)
        fig.update_layout(title="Certificados por periodo y tasa por alumno")
        show(fig, height=420)
        with st.expander("Ver tabla por periodo"):
            st.dataframe(cpp, use_container_width=True, hide_index=True)

    st.subheader("Por marca")
    st.caption("Siempre las cuatro universidades: es una comparación.")
    st.dataframe(R["cert_marca"], use_container_width=True, hide_index=True)


# ==================================================================
# CATÁLOGO: uso contra fecha de creación
# ==================================================================
elif seccion == "Catálogo":
    st.header(TITULOS[seccion])
    st.caption(f"Fuente: snapshot usuario×LE, columna Fecha de creación · {etiqueta_marca}")
    cat = R["catalogo"]
    g, coh = cat["les"], cat["cohortes_creacion"]
    glosario(
        "Horas captadas por cada curso del catálogo contra su fecha de creación.",
        "Para cada LE se suman horas, inscripciones y alumnos del periodo, y se toma su "
        "**fecha de creación** de la propia exportación. Las cohortes de creación se calculan "
        "solas: cualquier fecha nueva que publique el proveedor entra sin tocar código.",
        {"Curso dormido": "menos de 1 h de consumo en el periodo.",
         "Cohorte de creación": "mes en que se creó la LE.",
         "Horas por LE": "se dan media y mediana porque la distribución está muy sesgada."})
    k = st.columns(4)
    k[0].metric("Cursos con consumo", fmt(cat["n_les"]))
    k[1].metric("Cursos dormidos (<1 h)", fmt(cat["n_dormidas"]),
                f"{cat['n_dormidas']/cat['n_les']*100:.0f}% del catálogo", delta_color="off")
    k[2].metric("Horas por curso", f"{cat['horas_por_le_media']:.1f}",
                f"mediana {cat['horas_por_le_mediana']:.1f}", delta_color="off")
    k[3].metric("Concentración top 5", f"{cat['share_top5']:.0f}%",
                f"top 10: {cat['share_top10']:.0f}%", delta_color="off")

    _g = g.dropna(subset=["creada"])
    fig = go.Figure()
    for dormida, color, nombre in [(False, AZUL, "Con uso (≥1 h)"), (True, GRIS_PREV, "Dormido (<1 h)")]:
        sub = _g[_g["dormida"] == dormida]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["creada"], y=sub["horas"], mode="markers", name=nombre,
            marker=dict(color=color, size=(sub["usuarios"] / max(_g["usuarios"].max(), 1) * 26 + 6),
                        line=dict(color="white", width=1)),
            customdata=list(zip(sub["Nombre de la LE"], sub["usuarios"], sub["plantilla"])),
            hovertemplate="%{customdata[0]}<br>Creada %{x|%d-%b-%Y}<br>%{y:,.1f} h<br>"
                          "%{customdata[1]:,.0f} alumnos<br>Formato %{customdata[2]}<extra></extra>"))
    fig.update_layout(title="Cada punto es un curso: cuándo se creó y cuántas horas capta "
                            "(tamaño = alumnos)",
                      xaxis_title="Fecha de creación", yaxis_title="Horas en el periodo")
    fig.update_yaxes(rangemode="tozero")
    show(fig, height=460)

    c1, c2 = st.columns(2)
    figa = go.Figure(go.Bar(x=coh["mes_ts"], y=coh["horas_por_le"], marker_color=AZUL,
                            customdata=list(zip(coh["les"], coh["horas"])),
                            hovertemplate="%{x|%b-%Y}<br>%{y:,.1f} h por curso<br>"
                                          "%{customdata[0]} cursos · %{customdata[1]:,.0f} h<extra></extra>"))
    figa.update_layout(title="Horas por curso según su mes de creación",
                       yaxis_title="Horas / curso", xaxis_title="Mes de creación")
    figa.update_yaxes(rangemode="tozero")
    with c1:
        show(figa, height=360)
    figb = go.Figure()
    figb.add_trace(go.Bar(name="Con uso", x=coh["mes_ts"], y=coh["les"] - coh["dormidas"],
                          marker_color=AZUL))
    figb.add_trace(go.Bar(name="Dormidos", x=coh["mes_ts"], y=coh["dormidas"], marker_color=GRIS_PREV))
    figb.update_layout(barmode="stack", title="Cursos creados cada mes y cuántos están dormidos",
                       yaxis_title="Cursos", xaxis_title="Mes de creación")
    figb.update_yaxes(rangemode="tozero")
    with c2:
        show(figb, height=360)

    with st.expander("Ver catálogo completo"):
        _cols = [c for c in ["Nombre de la LE", "creada", "plantilla", "horas", "usuarios",
                             "inscripciones", "horas_por_usuario", "avance_mediana",
                             "certificados", "delta"] if c in g.columns]
        st.dataframe(g[_cols].round(2), use_container_width=True, hide_index=True)


# ==================================================================
# FORMATO (plantilla)
# ==================================================================
elif seccion == "Formato":
    st.header(TITULOS[seccion])
    st.caption(f"Fuente: snapshot usuario×LE, columna Plantilla · {etiqueta_marca}")
    fm = R["formato"]
    if fm.empty:
        st.info("Sin datos de formato en esta selección.")
    else:
        glosario(
            "Horas de consumo por inscripción, según el formato con el que se construyó el curso.",
            "`Plantilla` es el formato con el que se construyó la LE. Se dan horas totales, "
            "horas por inscripción (media) y horas por alumno (mediana), más el reparto de avance "
            "máximo por par (usuario, LE).",
            {"Inscripción": "una fila usuario×LE, aunque tenga 0 h.",
             "openModule / standardUnit": "los dos formatos más frecuentes del catálogo.",
             "Media y mediana": "la mediana por alumno suele ser 0: la mayoría de las "
                                "inscripciones no registran horas."})
        k = st.columns(3)
        k[0].metric("Formatos en uso", fmt(len(fm)))
        k[1].metric("Inscripciones", fmt(fm["inscripciones"].sum()))
        k[2].metric("Cursos", fmt(fm["les"].sum()))

        _f = fm.sort_values("h_por_inscripcion_media")
        fig = go.Figure(go.Bar(x=_f["h_por_inscripcion_media"] * 60, y=_f["Plantilla"],
                               orientation="h", marker_color=AZUL,
                               text=[f"{v*60:.1f} min" for v in _f["h_por_inscripcion_media"]],
                               textposition="outside",
                               customdata=list(zip(_f["inscripciones"], _f["horas"], _f["les"])),
                               hovertemplate="%{y}<br>%{x:.1f} min por inscripción<br>"
                                             "%{customdata[0]:,.0f} inscripciones · "
                                             "%{customdata[1]:,.0f} h · %{customdata[2]} cursos<extra></extra>"))
        fig.update_layout(title="Minutos de consumo por inscripción, según formato",
                          xaxis_title="Minutos por inscripción",
                          xaxis_range=[0, float(_f["h_por_inscripcion_media"].max()) * 60 * 1.35])
        show(fig, height=340)

        c1, c2 = st.columns(2)
        # Los dos paneles comparten escala 0-100: son el mismo reparto visto por
        # sus dos extremos y con ejes libres una barra corta parecia larga.
        figa = go.Figure(go.Bar(x=_f["bajo20"], y=_f["Plantilla"], orientation="h",
                                marker_color=AZUL,
                                text=[f"{v:.0f}%" for v in _f["bajo20"]], textposition="inside",
                                insidetextfont=dict(color="white")))
        figa.update_layout(title="No pasa del 20% del curso", xaxis_title="% de pares",
                           xaxis_range=[0, 100])
        with c1:
            show(figa, height=330)
        figb = go.Figure(go.Bar(x=_f["alto80"], y=_f["Plantilla"], orientation="h",
                                marker_color=AZUL_CLARO,
                                text=[f"{v:.1f}%" for v in _f["alto80"]], textposition="outside"))
        figb.update_layout(title="Llega al 80% o más", xaxis_title="% de pares",
                           xaxis_range=[0, 100])
        with c2:
            show(figb, height=330)
        with st.expander("Ver tabla"):
            st.dataframe(fm.round(3), use_container_width=True, hide_index=True)


# ==================================================================
# RUTA MÁSTER
# ==================================================================
elif seccion == "Ruta Máster":
    st.header(TITULOS[seccion])
    st.caption(f"Los 18 cursos de la ruta, mapeados al catálogo por nombre · {etiqueta_marca}")
    ru, rp = R["ruta"], R["ruta_prev"]
    pc = ru["por_curso"]
    if pc.empty:
        st.info("Ninguno de los cursos de la ruta aparece en esta selección.")
    else:
        st.caption(f"Los {ru['n_cursos_encontrados']} cursos de la ruta concentran el "
                   f"{ru['pct_horas_plataforma']:.0f}% de las horas del periodo. Mediana por "
                   f"alumno: inscrito en {ru['inscritos_mediana']:.0f} de {ru['n_cursos_ruta']}, "
                   f"consume {ru['cobertura_mediana']:.0f}.")
        glosario(
            "Cómo avanza la Ruta de Máster en IA: por curso y por alumno.",
            "Los 18 nombres que entregó Academia se casan con el catálogo por nombre normalizado "
            "(hoy resuelven 18 de 18). Por curso se dan alumnos, horas y % que llega al tramo "
            "80-100%. Por alumno se cuenta cuántos de los 18 toca (cobertura) y cuántos completa.",
            {"Cobertura": "cursos distintos de la ruta que el alumno consume (horas > 0).",
             "Completado": "el alumno llega al tramo 80-100% de ese curso.",
             "Ruta terminada": "alumnos con los 18 cursos en tramo 80-100%.",
             "Mapeo": "por nombre normalizado, no por ID. La lista vive en `RUTA_MASTER` "
                      "(pipeline.py)."})
        if ru["no_encontrados"]:
            st.warning("Sin match en el catálogo: " + ", ".join(ru["no_encontrados"]))

        k = st.columns(4)
        k[0].metric("Alumnos en la ruta", fmt(ru["usuarios"]))
        k[1].metric("Cursos de la ruta consumidos", f"{ru['cobertura_media']:.1f}",
                    f"inscritos en {ru['inscritos_media']:.1f} de {ru['n_cursos_ruta']}",
                    delta_color="off")
        k[2].metric("Horas en la ruta por alumno", f"{ru['horas_media']*60:.0f} min",
                    f"mediana {ru['horas_mediana']*60:.0f} min", delta_color="off")
        k[3].metric("Rutas completadas", fmt(ru["ruta_terminada"]),
                    delta_txt(mom_pct(ru["ruta_terminada"], rp["ruta_terminada"])))

        # Un panel por metrica: alumnos y % completado no comparten unidad.
        _o = pc.iloc[::-1]
        c1, c2 = st.columns(2)
        figa = go.Figure(go.Bar(x=_o["usuarios"], y=[corto(s, 40) for s in _o["curso_ruta"]],
                                orientation="h", marker_color=AZUL,
                                text=[fmt(v) for v in _o["usuarios"]], textposition="auto",
                                customdata=list(zip(_o["curso_ruta"], _o["horas"])),
                                hovertemplate="%{customdata[0]}<br>%{x:,.0f} alumnos<br>"
                                              "%{customdata[1]:,.1f} h<extra></extra>"))
        figa.update_layout(title="Alumnos por curso de la ruta", xaxis_title="Alumnos")
        figa.update_xaxes(rangemode="tozero")
        with c1:
            show(figa, height=560)
        figb = go.Figure(go.Bar(x=_o["completado_pct"], y=[corto(s, 40) for s in _o["curso_ruta"]],
                                orientation="h", marker_color=AZUL_CLARO,
                                text=[f"{v:.1f}%" for v in _o["completado_pct"]],
                                textposition="outside",
                                customdata=list(zip(_o["curso_ruta"], _o["certificados"])),
                                hovertemplate="%{customdata[0]}<br>%{x:.1f}% llega al 80-100%<br>"
                                              "%{customdata[1]:,.0f} certificados<extra></extra>"))
        figb.update_layout(title="% de alumnos que completa cada curso", xaxis_title="% completado",
                           xaxis_range=[0, float(pc["completado_pct"].max()) * 1.4])
        with c2:
            show(figb, height=560)

        st.subheader("Cuántos cursos de la ruta consume cada alumno")
        st.caption("«Consumido» es con horas > 0, no inscrito: la asignación es masiva y casi "
                   "todos los alumnos aparecen inscritos en la ruta entera.")
        dcob, dcom = ru["dist_cobertura"], ru["dist_completos"]
        fig = go.Figure()
        fig.add_trace(go.Bar(name="Cursos consumidos", x=list(dcob.index), y=list(dcob.values),
                             marker_color=AZUL))
        fig.add_trace(go.Bar(name="Cursos completados", x=list(dcom.index), y=list(dcom.values),
                             marker_color=GRIS_PREV))
        fig.update_layout(barmode="group", xaxis_title="Cursos de la ruta (de 18)",
                          yaxis_title="Alumnos", bargap=0.2)
        fig.update_yaxes(rangemode="tozero")
        show(fig, height=380)
        with st.expander("Ver tabla por curso"):
            st.dataframe(pc.drop(columns=["orden"]).round(2), use_container_width=True,
                         hide_index=True)


# ==================================================================
# CENTRO Y NIVEL
# ==================================================================
elif seccion == "Centro y Nivel":
    st.header(TITULOS[seccion])
    st.caption(f"Centro inferido del dominio del correo · Nivel del propio export · {etiqueta_marca}")
    ce, ni = R["centro"], R["nivel"]
    if "pct_licencia_efectiva" in ce.columns and ce["pct_licencia_efectiva"].notna().any():
        _alto = ce.loc[ce["pct_licencia_efectiva"].idxmax()]
        _bajo = ce.loc[ce["pct_licencia_efectiva"].idxmin()]
        st.caption(f"Activación sobre licencia: de {_alto['pct_licencia_efectiva']:.1f}% en "
                   f"{_alto['Centro']} a {_bajo['pct_licencia_efectiva']:.1f}% en "
                   f"{_bajo['Centro']}.")
    glosario(
        "El mismo tablero cortado por centro educativo y por nivel.",
        "El **Centro** se infiere del dominio del correo (el mapeo dominio a centro es uno a uno "
        "en toda la base y rellena el ~0.6% de nulos del proveedor). El **Nivel** viene en el "
        "export. Las licencias salen del roster, así que la activación se mide sobre la base real "
        "de cada centro.",
        {"% licencia inscrita": "usuarios del centro con alguna inscripción / licencias del centro.",
         "% licencia efectiva": "usuarios del centro con más de 0 h / licencias del centro.",
         "Media y mediana": "horas por usuario activado, expresadas en minutos."})

    for etiqueta, df, col in [("Por centro", ce, "Centro"), ("Por nivel", ni, "Nivel")]:
        st.subheader(etiqueta)
        _x = df[col]
        cols_fig = st.columns(2)
        if "pct_licencia_efectiva" in df.columns and df["pct_licencia_efectiva"].notna().any():
            figa = go.Figure()
            figa.add_trace(go.Bar(name="% licencia inscrita", x=_x, y=df["pct_licencia_inscrita"],
                                  marker_color=GRIS_PREV))
            figa.add_trace(go.Bar(name="% licencia efectiva", x=_x, y=df["pct_licencia_efectiva"],
                                  marker_color=AZUL))
            figa.update_layout(barmode="group", title="Activación sobre licencias",
                               yaxis_title="% de licencias", bargap=0.3)
            figa.update_yaxes(rangemode="tozero")
            with cols_fig[0]:
                show(figa, height=340)
        figb = go.Figure()
        figb.add_trace(go.Bar(name="Media", x=_x, y=df["media_act"] * 60, marker_color=AZUL_CLARO))
        figb.add_trace(go.Bar(name="Mediana", x=_x, y=df["mediana_act"] * 60, marker_color=AZUL))
        figb.update_layout(barmode="group", title="Minutos por alumno activado",
                           yaxis_title="Minutos", bargap=0.3)
        figb.update_yaxes(rangemode="tozero")
        with cols_fig[1]:
            show(figb, height=340)
        st.dataframe(df.round(2), use_container_width=True, hide_index=True)
