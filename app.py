"""
Dashboard PottencIA / ODILO: versión interactiva del deck mensual del comité.

Reemplaza las presentaciones fijas (Datos PottencIA - <fecha>.pptx). Se actualiza
solo con reemplazar los CSV que Santiago descarga del proveedor Odilo BI en las
carpetas mnt/data/current, mnt/data/previous y datos_analisis_estrategico_2026.

Ejecutar:  streamlit run dashboard/app.py
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import pipeline as pl

st.set_page_config(page_title="PottencIA · Dashboard", page_icon="📊",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
  .block-container {padding-top: 4.5rem; max-width: 1500px;}
  h1 {font-size: 2.0rem !important; letter-spacing: -0.02em; margin-bottom: 0.2rem;}
  h2 {font-size: 1.25rem !important; font-weight: 600; margin-top: 2.2rem;}
  h3 {font-size: 1.02rem !important; font-weight: 600; color: #43506b;}
  /* Los valores de KPI mandan; la etiqueta acompanna. */
  [data-testid="stMetricValue"] {font-size: 2.1rem; font-weight: 600;}
  [data-testid="stMetricLabel"] p {font-size: 0.86rem; color: #5a6478;}
  [data-testid="stMetricDelta"] {font-size: 0.92rem;}
  /* El glosario es apoyo, no protagonista. */
  [data-testid="stExpander"] summary p {font-size: 0.86rem; color: #5a6478;}
  [data-testid="stExpander"] details {border-color: #e6e9ee;}
  hr {margin: 0.9rem 0 1.4rem 0;}
</style>
""", unsafe_allow_html=True)

# ---- Paleta ----
# El color NO decora: azul = periodo actual, gris = periodo anterior,
# verde/rojo solo para signo (mejora / empeora). Las marcas NO tienen color
# propio: cuando cada universidad tenia el suyo, naranja y verde se leian
# como semaforo y eso no significaba nada.
AZUL = "#1f6fb2"
AZUL_CLARO = "#7fb3da"
VERDE = "#2f7d32"
ROJO = "#b3261e"
GRIS = "#8a94a6"
GRIS_PREV = "#c9d2de"
TINTA = "#14213d"
SEG_COLORS = {"Exploradores": "#dce4ee", "Constantes": "#9ec3e0",
              "Intensivos": "#4a90c2", "Power users": "#1f4e79"}


def color_signo(v):
    """Verde si mejora, rojo si empeora. Unico uso legitimo de verde/rojo."""
    return VERDE if v > 0 else (ROJO if v < 0 else GRIS)


# ---- Estilo unificado: fondo BLANCO + rejilla tenue (arregla el "fondo gris") ----
def show(fig, height=420):
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="white", plot_bgcolor="white",
        font=dict(size=13, color="#1a1a1a"),
        margin=dict(l=45, r=25, t=55, b=45),
        height=height,
        legend=dict(bgcolor="rgba(255,255,255,0.7)", bordercolor="#e6e9ee", borderwidth=1),
        title_font=dict(size=15),
    )
    if fig.layout.title.text is None:
        fig.update_layout(title_text="")
    # Sin esto, el texto "outside" de las barras altas se recorta contra el eje.
    fig.update_traces(cliponaxis=False, selector=dict(type="bar"))
    fig.update_xaxes(gridcolor="#eef1f5", zerolinecolor="#dfe3e8", linecolor="#dfe3e8")
    fig.update_yaxes(gridcolor="#eef1f5", zerolinecolor="#dfe3e8", linecolor="#dfe3e8")
    st.plotly_chart(fig, use_container_width=True)


def titular(texto, tono="neutro"):
    """Frase que dice la conclusion de la seccion, bajo el titulo.

    El titulo nombra la metrica; esto dice que pasa con ella. Se calcula a
    partir de los datos, asi que cambia cada mes sin tocar el codigo.
    """
    color = {"malo": ROJO, "bueno": VERDE, "neutro": TINTA}[tono]
    st.markdown(
        f"<p style='font-size:1.15rem;line-height:1.5;color:{color};"
        f"margin:0.1rem 0 1.1rem 0;max-width:62ch'>{texto}</p>",
        unsafe_allow_html=True)


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
@st.cache_data(show_spinner="Cargando y limpiando los CSV del proveedor…")
def load_base(_token: float):
    return pl.cargar_base()


@st.cache_data(show_spinner="Calculando agregados…")
def compute(_token: float, marcas_key: tuple):
    base = load_base(_token)
    marcas = list(marcas_key) if marcas_key else None
    return pl.computar(base, marcas)


# ==================================================================
# Sidebar
# ==================================================================
st.sidebar.title("PottencIA")
st.sidebar.caption("Dashboard del comité · ODILO")

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
# Etiquetas cortas para la barra; el título largo vive en la cabecera de cada sección.
SECCIONES = [
    "Panorama", "Tendencias", "Segmentos", "Abandono", "Cursos",
    "Pulso", "Crecimiento", "Cohortes", "Lift",
]
TITULOS = {
    "Panorama": "Panorama del periodo",
    "Tendencias": "Tendencias diarias del periodo actual",
    "Segmentos": "Segmentación de usuarios por intensidad de uso",
    "Abandono": "Avance y abandono en las experiencias",
    "Cursos": "Cursos (Learning Experiences)",
    "Pulso": "El pulso de la plataforma",
    "Crecimiento": "Crecimiento de la base de usuarios",
    "Cohortes": "Retención por cohorte",
    "Lift": "Lift de retención: qué contenido hace que vuelvan",
}

seccion = st.segmented_control(
    "Sección", SECCIONES, default=SECCIONES[0],
    label_visibility="collapsed", key="nav")
if seccion is None:                      # evita el estado vacío al deseleccionar
    seccion = SECCIONES[0]

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
if seccion == SECCIONES[0]:
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

    _d = pan.set_index("kpi")["delta_pct"]
    _horas = _d.get("Horas consumidas")
    _seg = _d.get("Usuarios efectivos", _d.get("Usuarios con consumo"))
    _nom_seg = "usuarios efectivos" if es_global else "usuarios con consumo"
    if pd.notna(_horas) and pd.notna(_seg) and _horas < -5 and _seg < -5:
        titular(f"Contracción real de uso: las horas caen {abs(_horas):.1f}% y los "
                f"{_nom_seg} {abs(_seg):.1f}%. No es un problema de catálogo, es menos "
                f"gente consumiendo menos.", "malo")
    elif pd.notna(_horas) and _horas > 5:
        titular(f"El consumo crece {_horas:.1f}% contra el periodo anterior.", "bueno")
    else:
        titular("El consumo se mantiene plano contra el periodo anterior.")

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
elif seccion == SECCIONES[1]:
    st.header(TITULOS[seccion])
    st.caption("Fuente: serie diaria de plataforma (global, sin desglose por marca)")
    _t = R["tendencias"]
    _h = _t["horas"].dropna(subset=["rolling_7d"])
    if not _h.empty:
        _ult = float(_h["rolling_7d"].iloc[-1])
        _ref = float(_t["horas_prev_avg"])
        _dif = (_ult / _ref - 1) * 100 if _ref else float("nan")
        _dias = int((_h["rolling_7d"] < _ref).sum())
        if pd.notna(_dif) and _dif < -5:
            titular(f"El ritmo actual está {abs(_dif):.0f}% por debajo del promedio diario "
                    f"del periodo anterior, y lleva {_dias} de {len(_h)} días debajo de esa "
                    f"línea. Es tendencia sostenida, no un mal día.", "malo")
        elif pd.notna(_dif) and _dif > 5:
            titular(f"El ritmo actual está {_dif:.0f}% por encima del promedio diario "
                    f"del periodo anterior.", "bueno")
        else:
            titular("El ritmo diario se mantiene en línea con el periodo anterior.")
    glosario(
        "El ritmo día a día del periodo actual comparado con el promedio diario del anterior.",
        "Línea = media móvil de 7 días de la serie diaria. Línea gris punteada = promedio "
        "diario del periodo anterior.",
        {"Rolling 7d": "suaviza el ruido diario promediando cada día con los 6 previos.",
         "Promedio periodo ant.": "referencia fija para ver si el periodo actual va mejor o peor."})
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
    c1, c2 = st.columns(2)
    c1.metric("Prom. diario horas (periodo ant.)", fmt(t["horas_prev_avg"], 0))
    c2.metric("Prom. diario contenidos (periodo ant.)", fmt(t["contenidos_prev_avg"], 0))


# ==================================================================
# ③ SEGMENTACIÓN
# ==================================================================
elif seccion == SECCIONES[2]:
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
    _noact = float(act.get("No activados", float("nan")))
    _explo = float(inten.get("Exploradores", float("nan")))
    if pd.notna(_noact) and pd.notna(_explo):
        titular(f"El problema es profundidad, no activación: {_noact*100:.0f}% no se activa, "
                f"pero de los que sí, {_explo*100:.0f}% no pasa de una hora. Casi nadie "
                f"llega a uso intensivo.", "malo")

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
        # La conclusion suele ser "las cuatro marcas se comportan igual". Se
        # mide la dispersion y se dice, en vez de gastar media pantalla en
        # cuatro barras apiladas visualmente idénticas.
        disp = (sm["Exploradores"].max() - sm["Exploradores"].min()) * 100
        if disp < 8:
            st.caption(f"Las marcas se comportan igual: el % de exploradores solo varía "
                       f"{disp:.1f} puntos entre la más alta y la más baja. La palanca de "
                       f"profundidad es de producto, no de campus.")
        else:
            _alta = sm.loc[sm["Exploradores"].idxmax(), "Universidad"]
            _baja = sm.loc[sm["Exploradores"].idxmin(), "Universidad"]
            st.caption(f"Hay diferencia real entre marcas: {disp:.1f} puntos de brecha en "
                       f"% de exploradores entre {_alta} y {_baja}.")
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
elif seccion == SECCIONES[3]:
    st.header(TITULOS[seccion])
    st.caption(f"Fuente: snapshot usuario×LE · {etiqueta_marca}")
    _ab, _abp = R["abandono_cur"], R["abandono_prev"]
    _b20 = _ab["pct_bajo20"] * 100
    _db = (_ab["pct_bajo20"] - _abp["pct_bajo20"]) * 100
    _a80 = _ab["pct_alto80"] * 100
    titular(f"{_b20:.1f}% de las inscripciones no pasa del primer 20% del curso "
            f"({_db:+.1f} puntos vs el periodo anterior) y solo {_a80:.1f}% llega al 80%. "
            f"El abandono se decide en el arranque.",
            "malo" if _db > 0 else "neutro")
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
elif seccion == SECCIONES[4]:
    st.header(TITULOS[seccion])
    st.caption(f"Fuente: snapshot usuario×LE · {etiqueta_marca}")
    _tl = R["top_les"]
    _th, _tm, _bc = _tl["top_horas"], _tl["top_mejora"], _tl["bottom_caida"]
    if not _th.empty:
        _lider = _th.iloc[0]
        _peor = _bc.iloc[0] if not _bc.empty else None
        _mejor = _tm.iloc[0] if not _tm.empty else None
        _msg = (f"«{corto(_lider['Nombre de la LE'], 60)}» concentra "
                f"{_lider['horas_cur']:,.0f} h, el {_lider['horas_cur']/_th['horas_cur'].sum()*100:.0f}% "
                f"del top 5.")
        if _peor is not None and _mejor is not None:
            _msg += (f" Las caídas pesan más que las subidas: la mayor caída es de "
                     f"{abs(_peor['delta']):,.0f} h contra {_mejor['delta']:+,.0f} h de la mayor subida.")
        titular(_msg, "malo" if (_peor is not None and _mejor is not None
                                 and abs(_peor["delta"]) > _mejor["delta"]) else "neutro")
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
elif seccion == SECCIONES[5]:
    st.header(TITULOS[seccion])
    st.caption("Serie diaria de horas (global) · rolling 7d, tendencia 28d e índice estacional")
    _s = R["serie_larga"].dropna(subset=["r7"])
    if len(_s) > 60:
        _pico = _s.loc[_s["r7"].idxmax()]
        _hoy = float(_s["r7"].iloc[-1])
        _caida = (_hoy / float(_pico["r7"]) - 1) * 100
        titular(f"El pico fue el {_pico['fecha']:%d-%b-%Y} con {_pico['r7']:,.0f} h/día. "
                f"Hoy la plataforma corre {abs(_caida):.0f}% por debajo de ese máximo.",
                "malo" if _caida < -20 else "neutro")
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
    fig.add_trace(go.Scatter(x=s["fecha"], y=s["idx_estacional"], line=dict(color="#c2cbd8", width=0.5),
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
elif seccion == SECCIONES[6]:
    st.header(TITULOS[seccion])
    st.caption(f"Composición de los usuarios activos de cada mes · {etiqueta_marca}")
    _ga = R["growth"]
    if len(_ga) >= 2:
        _u = _ga.iloc[-1]
        _pct_rec = _u["Recurrentes"] / _u["Total activos"] * 100 if _u["Total activos"] else float("nan")
        _neto = _u["Nuevos"] + _u["Reactivados"] - _u["Perdidos"]
        titular(f"En {_u['eje']} solo {_pct_rec:.0f}% de los activos son recurrentes y se "
                f"pierden {_u['Perdidos']:,.0f} usuarios contra {_u['Nuevos']:,.0f} nuevos: "
                f"saldo neto {_neto:+,.0f}. El problema es retención, no adquisición.",
                "malo" if _neto < 0 else "neutro")
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
    for col, color in [("Recurrentes", "#1f4e79"), ("Reactivados", "#4a90c2"), ("Nuevos", "#c5dcee")]:
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
        for col, color in [("Recurrentes", "#1f4e79"), ("Reactivados", "#4a90c2"), ("Nuevos", "#c5dcee")]:
            fig2.add_trace(go.Bar(name=col, x=g["eje"], y=g[col],
                                  marker=dict(color=color, opacity=_op),
                                  showlegend=(rr == 1 and cc == 1)), row=rr, col=cc)
    fig2.update_layout(barmode="stack")
    show(fig2, height=620)


# ==================================================================
# ⑧ COHORTES
# ==================================================================
elif seccion == SECCIONES[7]:
    st.header(TITULOS[seccion])
    st.caption(f"% de cada cohorte que sigue activo N periodos después · {etiqueta_marca}")
    _coh = R["cohortes"]
    if "m1" in _coh.columns and _coh["m1"].notna().any():
        _m1 = _coh["m1"].dropna()
        titular(f"El acantilado está en el primer periodo: de media solo vuelve "
                f"{_m1.mean()*100:.0f}% de cada cohorte, y la mejor apenas llega a "
                f"{_m1.max()*100:.0f}%. Las cohortes nuevas no aguantan más que las viejas.",
                "malo")
    glosario(
        "Cuánto aguanta cada 'generación' de usuarios según el mes en que se activó por primera vez.",
        "Se agrupa a los usuarios por su mes de primera actividad (cohorte) y se mide qué "
        "porcentaje sigue activo 1, 2, 3… periodos después. m0 siempre es 100%.",
        {"Cohorte": "todos los que se activaron por primera vez el mismo mes.",
         "+N": "N periodos después de la primera actividad.",
         "Acantilado": "la caída brusca típica del periodo +1."})
    coh = R["cohortes"]
    mcols = [c for c in coh.columns if c.startswith("m")]

    z = coh[mcols].values.astype(float) * 100
    fig = go.Figure(go.Heatmap(
        z=z, x=[f"+{i}" for i in range(len(mcols))],
        y=[f"{r.Cohorte} (n={int(r.n):,})" for r in coh.itertuples()],
        colorscale="Blues", zmin=0, zmax=float(np.nanmax(z[:, 1:])) if z.shape[1] > 1 else 100,
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
        _mix = 0.18 + 0.82 * (i / (_tot - 1))
        _col = f"rgb({int(198 - 167*_mix)},{int(220 - 142*_mix)},{int(238 - 117*_mix)})"
        figc.add_trace(go.Scatter(x=list(range(len(mcols))), y=ys, mode="lines+markers",
                                  line=dict(color=_col, width=2),
                                  marker=dict(color=_col, size=6), name=r.Cohorte))
    figc.update_layout(title="Curvas de vida", yaxis_title="% de la cohorte activo",
                       xaxis_title="Periodos desde la primera actividad")
    show(figc, height=420)


# ==================================================================
# ⑨ LIFT DE RETENCIÓN (métrica del análisis estratégico)
# ==================================================================
elif seccion == SECCIONES[8]:
    st.header(TITULOS[seccion])
    st.caption(f"Métrica del análisis estratégico (observada vs. esperada) · {etiqueta_marca}")
    _lf = R["lift_estrategico"]
    if not _lf.empty:
        _g0, _c0 = _lf.iloc[0], _lf.iloc[-1]
        titular(f"Sobre una base de retorno de {R['base_ret']:.0f}%, "
                f"«{corto(_g0['Nombre de la LE'], 52)}» retiene {_g0['lift_pp']:+.1f} puntos y "
                f"«{corto(_c0['Nombre de la LE'], 52)}» {_c0['lift_pp']:+.1f} puntos. Son "
                f"{_g0['lift_pp'] - _c0['lift_pp']:.0f} puntos de diferencia según con qué "
                f"curso se topa el usuario: el contenido sí mueve la aguja.")
    glosario(
        "Qué cursos retienen a la gente por encima de lo normal (gancho) y cuáles por debajo (callejón).",
        "Para cada curso: **retención observada** = % de sus consumidores de un mes que siguen "
        "activos (en cualquier curso) el mes siguiente, agrupando todos los meses. "
        "**Retención esperada** = tasa base global de retorno de la plataforma. "
        "**Lift (pp)** = observada − esperada. Solo cursos con ≥100 transiciones-usuario.",
        {"Lift (pp)": "puntos porcentuales por encima/debajo de la base. +10 pp = retiene 10 puntos más que el promedio.",
         "Base esperada": f"tasa global de retorno mes→mes ({R['base_ret']:.1f}% en esta selección).",
         "Gancho": "lift positivo: engancha y hace volver.",
         "Callejón": "lift negativo: se consume y la gente no regresa.",
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
            "transiciones, y es más estable y comparable entre cursos. Aquí tienes ambas para referencia:")
        if not R["lift_deck"].empty:
            st.dataframe(R["lift_deck"].round(2), use_container_width=True, hide_index=True)
