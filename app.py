"""
Dashboard PottencIA / ODILO — versión interactiva del deck mensual del comité.

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

# ---- Paleta corporativa ----
AZUL = "#1f77b4"
NARANJA = "#ff7f0e"
VERDE = "#2ca02c"
ROJO = "#d62728"
GRIS = "#8a94a6"
SEG_COLORS = {"Exploradores": "#cfd8e3", "Constantes": "#9ecae1",
              "Intensivos": "#5aa3d4", "Power users": "#1f6fb2"}
MARCA_COLORS = {"UANE": "#1f77b4", "UTC": "#ff7f0e", "ULA": "#2ca02c", "UTEG": "#9467bd"}


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
    fig.update_xaxes(gridcolor="#eef1f5", zerolinecolor="#dfe3e8", linecolor="#dfe3e8")
    fig.update_yaxes(gridcolor="#eef1f5", zerolinecolor="#dfe3e8", linecolor="#dfe3e8")
    st.plotly_chart(fig, use_container_width=True)


def glosario(que_es: str, como_se_calcula: str, terminos: dict | None = None,
             decision: str | None = None):
    """Bloque de contexto que acompaña a cada gráfica."""
    with st.expander("📖 Cómo leer esto · cómo se calcula · glosario", expanded=False):
        st.markdown(f"**Qué muestra** — {que_es}")
        st.markdown(f"**Cómo se calcula** — {como_se_calcula}")
        if terminos:
            st.markdown("**Glosario**")
            for k, v in terminos.items():
                st.markdown(f"- **{k}:** {v}")
        if decision:
            st.markdown(f"**Decisión que habilita** — {decision}")


def fmt(v, dec=0):
    if pd.isna(v):
        return "—"
    return f"{v:,.{dec}f}"


def flecha(delta):
    if pd.isna(delta):
        return "•"
    return "▲" if delta > 0 else ("▼" if delta < 0 else "•")


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
st.sidebar.title("📊 PottencIA")
st.sidebar.caption("Dashboard del comité · ODILO")

if "reload_token" not in st.session_state:
    st.session_state.reload_token = 0.0
if st.sidebar.button("🔄 Recargar datos", use_container_width=True):
    st.cache_data.clear()
    st.session_state.reload_token += 1

try:
    BASE = load_base(st.session_state.reload_token)
except FileNotFoundError as e:
    st.error(f"No se encontraron los CSV esperados.\n\n{e}\n\n"
             "Revisa que `mnt/data/current`, `mnt/data/previous` y "
             "`datos_analisis_estrategico_2026` contengan los exports del proveedor.")
    st.stop()

meta = BASE["meta"]

# ---- Filtro de MARCA (global, aplica donde tiene sentido) ----
st.sidebar.markdown("### 🎓 Marca")
marcas_sel = st.sidebar.multiselect(
    "Filtrar por universidad", BASE["marcas"], default=BASE["marcas"],
    help="Aplica a segmentación, abandono, cursos, growth, cohortes y lift. "
         "Los KPIs de panorama y las tendencias diarias salen de la serie diaria "
         "de plataforma (sin desglose por marca) y se mantienen globales.")
if not marcas_sel:
    marcas_sel = BASE["marcas"]
es_global = set(marcas_sel) == set(BASE["marcas"])
marcas_key = None if es_global else tuple(sorted(marcas_sel))

R = compute(st.session_state.reload_token, marcas_key)

st.sidebar.markdown(f"**Mes actual:** {meta['cur_label']}")
st.sidebar.markdown(f"**Mes anterior:** {meta['prev_label']}")
if not es_global:
    st.sidebar.info("Filtro activo: **" + ", ".join(marcas_sel) + "**")
st.sidebar.caption(f"Generado {meta['generado']}")

SECCIONES = [
    "① Panorama del mes",
    "② Tendencias diarias",
    "③ Segmentación de usuarios",
    "④ Avance y abandono",
    "⑤ Cursos (LEs)",
    "⑥ El pulso (serie larga)",
    "⑦ Growth accounting",
    "⑧ Retención por cohorte",
    "⑨ Lift de retención (gancho vs callejón)",
]
seccion = st.sidebar.radio("Secciones", SECCIONES, label_visibility="collapsed")

with st.sidebar.expander("ℹ️ Cómo actualizar cada semana"):
    st.markdown(
        "1. Descarga del portal Odilo BI los CSV del periodo.\n"
        "2. Mueve el `current` viejo a `previous/` y coloca el nuevo en `current/`.\n"
        "3. (Mensual) añade el snapshot del mes a `datos_analisis_estrategico_2026/`.\n"
        "4. Pulsa **🔄 Recargar datos**.")

etiqueta_marca = "todas las marcas" if es_global else ", ".join(marcas_sel)


# ==================================================================
# ① PANORAMA
# ==================================================================
if seccion == SECCIONES[0]:
    st.header("① Panorama del mes")
    st.caption(f"{meta['cur_label']} vs {meta['prev_label']} · fuente: serie diaria de plataforma (global)")
    glosario(
        "Los 4 KPIs de cabecera del mes y su variación contra el mes anterior.",
        "Suma de la **serie diaria de plataforma** del periodo. Δ% = (actual − anterior) / anterior. "
        "Usuarios efectivos se divide entre 2 (corrección de doble conteo heredada del deck).",
        {"Usuarios activos": "cualquier interacción registrada en el mes.",
         "Usuarios efectivos": "usuarios con consumo real (métrica más estricta del portal).",
         "Contenidos únicos": "recursos distintos consumidos (DISTINCT_COUNT)."},
        "Si horas y efectivos caen juntos, es contracción real de uso, no de catálogo.")

    pan = R["panorama"]
    cols = st.columns(4)
    for col, (_, r) in zip(cols, pan.iterrows()):
        col.metric(r["kpi"], fmt(r["actual"]),
                   f"{flecha(r['delta_pct'])} {fmt(r['delta_pct'], 1)}% vs mes ant.")

    fig = make_subplots(rows=1, cols=4, subplot_titles=list(pan["kpi"]))
    for i, (_, r) in enumerate(pan.iterrows(), start=1):
        fig.add_trace(go.Bar(x=["Anterior", "Actual"], y=[r["anterior"], r["actual"]],
                             marker_color=["#c9d2de", AZUL], showlegend=False,
                             text=[fmt(r["anterior"]), fmt(r["actual"])], textposition="outside"),
                      row=1, col=i)
    show(fig, height=360)

    st.subheader("Por marca")
    pm = R["panorama_marca"]
    if not es_global:
        pm = pm[pm["Universidad"].isin(marcas_sel)]
    fig2 = make_subplots(rows=1, cols=len(pm), subplot_titles=list(pm["Universidad"]))
    for i, (_, r) in enumerate(pm.iterrows(), start=1):
        cats = ["Horas", "Contenidos", "Usuarios"]
        cur = [r["Horas_actual"], r["Contenidos_actual"], r["Usuarios_actual"]]
        prev = [r["Horas_anterior"], r["Contenidos_anterior"], r["Usuarios_anterior"]]
        fig2.add_trace(go.Bar(x=cats, y=prev, name="Anterior", marker_color="#c9d2de",
                              showlegend=(i == 1)), row=1, col=i)
        fig2.add_trace(go.Bar(x=cats, y=cur, name="Actual",
                              marker_color=MARCA_COLORS.get(r["Universidad"], AZUL),
                              showlegend=(i == 1)), row=1, col=i)
    fig2.update_layout(barmode="group")
    show(fig2, height=380)
    with st.expander("Ver tabla"):
        st.dataframe(pm, use_container_width=True)


# ==================================================================
# ② TENDENCIAS DIARIAS
# ==================================================================
elif seccion == SECCIONES[1]:
    st.header("② Tendencias diarias del mes actual")
    st.caption("Fuente: serie diaria de plataforma (global, sin desglose por marca)")
    glosario(
        "El ritmo día a día del mes actual comparado con el promedio diario del mes anterior.",
        "Línea = media móvil de 7 días de la serie diaria. Línea gris punteada = promedio "
        "diario del mes anterior. Área verde/roja = por encima/debajo de ese promedio.",
        {"Rolling 7d": "suaviza el ruido diario promediando cada día con los 6 previos.",
         "Promedio mes ant.": "referencia fija para ver si el mes actual va mejor o peor."},
        "Detectar si una caída es puntual (un mal día) o una tendencia sostenida.")
    t = R["tendencias"]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        subplot_titles=["Horas consumidas / día", "Contenidos / día"])
    h, c = t["horas"], t["contenidos"]
    fig.add_trace(go.Scatter(x=h["fecha"], y=h["rolling_7d"], line=dict(color=AZUL, width=3),
                             name="Horas (7d)"), row=1, col=1)
    fig.add_hline(y=t["horas_prev_avg"], line=dict(color=GRIS, dash="dash"), row=1, col=1)
    fig.add_trace(go.Scatter(x=c["fecha"], y=c["rolling_7d"], line=dict(color=NARANJA, width=3),
                             name="Contenidos (7d)"), row=2, col=1)
    fig.add_hline(y=t["contenidos_prev_avg"], line=dict(color=GRIS, dash="dash"), row=2, col=1)
    show(fig, height=560)
    c1, c2 = st.columns(2)
    c1.metric("Prom. diario horas (mes ant.)", fmt(t["horas_prev_avg"], 0))
    c2.metric("Prom. diario contenidos (mes ant.)", fmt(t["contenidos_prev_avg"], 0))


# ==================================================================
# ③ SEGMENTACIÓN
# ==================================================================
elif seccion == SECCIONES[2]:
    st.header("③ Segmentación de usuarios por intensidad de uso")
    st.caption(f"Fuente: snapshot usuario×LE del mes actual · {etiqueta_marca}")
    glosario(
        "Cómo se reparten los usuarios entre no activados y los 4 niveles de intensidad.",
        "Se suman las horas por usuario en el mes y se clasifican por umbrales fijos de horas.",
        {"No activados": "0 horas en el mes.",
         "Exploradores": "0–1 h.", "Constantes": "1–5 h.",
         "Intensivos": "5–20 h.", "Power users": ">20 h."},
        "Saber si hay que atacar activación (muchos no activados) o profundidad (muchos exploradores).")
    seg = R["segmentacion_global"]

    c1, c2 = st.columns(2)
    act = seg["activacion"]
    fig1 = go.Figure(go.Pie(labels=list(act.index), values=list(act.values),
                            marker_colors=["#dfe4ea", VERDE], hole=0.5,
                            textinfo="label+percent"))
    fig1.update_layout(title="Activación")
    with c1:
        show(fig1, height=380)

    inten = seg["intensidad"]
    fig2 = go.Figure(go.Bar(x=list(inten.values * 100), y=list(inten.index), orientation="h",
                            marker_color=[SEG_COLORS[s] for s in inten.index],
                            text=[f"{v*100:.1f}%" for v in inten.values], textposition="auto"))
    fig2.update_layout(title="Intensidad (entre los activados)",
                       yaxis=dict(categoryorder="array", categoryarray=pl.SEG_ORDER[::-1]),
                       xaxis_title="% de activados")
    with c2:
        show(fig2, height=380)

    st.subheader("Por marca")
    sm = R["segmentacion_marca"]
    if not es_global:
        sm = sm[sm["Universidad"].isin(marcas_sel)]
    if not sm.empty:
        fig3 = go.Figure()
        for s in pl.SEG_ORDER:
            fig3.add_trace(go.Bar(name=s, x=sm["Universidad"], y=sm[s] * 100,
                                  marker_color=SEG_COLORS[s]))
        fig3.update_layout(barmode="stack", yaxis_title="% de activados",
                           title="Mezcla de intensidad por marca")
        show(fig3, height=400)
        with st.expander("Ver tabla (incluye % No activados)"):
            st.dataframe(sm, use_container_width=True)


# ==================================================================
# ④ ABANDONO
# ==================================================================
elif seccion == SECCIONES[3]:
    st.header("④ Avance y abandono en las experiencias")
    st.caption(f"Fuente: snapshot usuario×LE · {etiqueta_marca}")
    glosario(
        "Hasta dónde llega la gente en los cursos: se quedan al inicio o los terminan.",
        "Para cada par (usuario, curso) se toma su **máximo tramo** de avance y se cuenta "
        "cuántos pares caen en cada rango. Se compara la distribución del mes actual vs. anterior.",
        {"Par (usuario, curso)": "una inscripción concreta de una persona a un curso.",
         "Tramo": "banda de avance reportada por el portal (0–20, 20–50, 50–80, 80–100%).",
         "Abandono temprano": "% de pares que no pasan del 20%."},
        "Priorizar rediseño de los cursos donde casi nadie pasa del primer tramo.")
    ab, abp = R["abandono_cur"], R["abandono_prev"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Se quedan bajo 20%", f"{ab['pct_bajo20']*100:.1f}%",
              f"{(ab['pct_bajo20']-abp['pct_bajo20'])*100:+.1f} pp vs ant.", delta_color="inverse")
    c2.metric("Llegan a ≥80%", f"{ab['pct_alto80']*100:.1f}%",
              f"{(ab['pct_alto80']-abp['pct_alto80'])*100:+.1f} pp vs ant.")
    c3.metric("Pares (usuario, curso)", fmt(len(ab["detalle"])))

    tramos_lbl = {10: "0–20%", 35: "20–50%", 65: "50–80%", 90: "80–100%"}
    dc, dp = ab["dist_tramos"], abp["dist_tramos"]
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Actual", x=[tramos_lbl.get(i, i) for i in dc.index],
                         y=dc.values * 100, marker_color=AZUL,
                         text=[f"{v*100:.0f}%" for v in dc.values], textposition="outside"))
    fig.add_trace(go.Bar(name="Anterior", x=[tramos_lbl.get(i, i) for i in dp.index],
                         y=dp.values * 100, marker_color="#c9d2de"))
    fig.update_layout(barmode="group", yaxis_title="% de pares",
                      xaxis_title="Tramo de avance máximo")
    show(fig, height=430)


# ==================================================================
# ⑤ CURSOS (LEs)
# ==================================================================
elif seccion == SECCIONES[4]:
    st.header("⑤ Cursos (Learning Experiences)")
    st.caption(f"Fuente: snapshot usuario×LE · {etiqueta_marca}")
    glosario(
        "Qué cursos concentran las horas y cuáles suben o bajan respecto al mes anterior.",
        "Suma de horas por curso en el mes actual (Top 5) y diferencia de horas vs. el mes "
        "anterior (Δ). Solo entran en Δ los cursos con ≥1 h el mes anterior.",
        {"LE": "Learning Experience = un curso/club del catálogo (~83–120 LEs).",
         "Δ horas": "horas de este mes menos las del mes anterior."},
        "Reforzar los que crecen y revisar los que se desploman.")
    tl = R["top_les"]

    st.subheader("Top 5 por horas consumidas (mes actual)")
    th = tl["top_horas"].iloc[::-1]
    fig = go.Figure(go.Bar(x=th["horas_cur"], y=th["Nombre de la LE"], orientation="h",
                           marker_color=AZUL, text=[fmt(v) for v in th["horas_cur"]],
                           textposition="auto"))
    fig.update_layout(xaxis_title="Horas")
    show(fig, height=380)

    c1, c2 = st.columns(2)
    tm = tl["top_mejora"].iloc[::-1]
    figm = go.Figure(go.Bar(x=tm["delta"], y=tm["Nombre de la LE"], orientation="h",
                            marker_color=VERDE, text=[f"{v:+.0f}" for v in tm["delta"]],
                            textposition="auto"))
    figm.update_layout(title="Top 5 que más crecieron (Δ horas)")
    with c1:
        show(figm, height=360)
    bc = tl["bottom_caida"]
    figc = go.Figure(go.Bar(x=bc["delta"], y=bc["Nombre de la LE"], orientation="h",
                            marker_color=ROJO, text=[f"{v:+.0f}" for v in bc["delta"]],
                            textposition="auto"))
    figc.update_layout(title="Top 5 que más cayeron (Δ horas)")
    with c2:
        show(figc, height=360)


# ==================================================================
# ⑥ SERIE LARGA
# ==================================================================
elif seccion == SECCIONES[5]:
    st.header("⑥ El pulso de la plataforma")
    st.caption("Serie diaria de horas (global) · rolling 7d, tendencia 28d e índice estacional")
    glosario(
        "La serie diaria de horas desde Dic-2025, anotada con los eventos conocidos.",
        "Panel superior: media móvil de 7 días (azul) y tendencia de 28 días (gris). "
        "Panel inferior: índice = horas del día / tendencia 28d (>1 = por encima de su propia tendencia).",
        {"Tendencia 28d": "media móvil centrada de 4 semanas; el nivel 'normal' del momento.",
         "Índice estacional": "aísla los picos/valles de gestión de la estacionalidad del calendario.",
         "Carga masiva": "alta masiva de usuarios (Feb-2026), anotada en la serie."},
        "Atribuir subidas/bajadas a decisiones concretas, no al azar.")
    s = R["serie_larga"]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.65, 0.35],
                        subplot_titles=["Horas de aprendizaje / día",
                                        "Índice vs tendencia local (>1 = sobre su propia tendencia)"])
    fig.add_trace(go.Scatter(x=s["fecha"], y=s["r7"], line=dict(color=AZUL, width=2),
                             name="Horas/día (7d)"), row=1, col=1)
    fig.add_trace(go.Scatter(x=s["fecha"], y=s["r28"], line=dict(color=GRIS, width=1.5, dash="dash"),
                             name="Tendencia 28d"), row=1, col=1)
    fig.add_trace(go.Scatter(x=s["fecha"], y=s["idx_estacional"], line=dict(color="#b7c0cc", width=0.5),
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
    st.header("⑦ Growth accounting")
    st.caption(f"Composición de los usuarios activos de cada mes · {etiqueta_marca}")
    glosario(
        "De qué está hecha la base activa de cada mes: gente nueva, que repite, que vuelve o que se pierde.",
        "Para cada mes se clasifica a cada usuario activo según su historial: nuevo (primera vez), "
        "recurrente (activo el mes pasado), reactivado (activo antes pero no el mes pasado). "
        "Perdidos = activos el mes pasado que no lo están este mes.",
        {"Nuevos": "se activan por primera vez.",
         "Recurrentes": "activos dos meses seguidos.",
         "Reactivados": "vuelven tras una pausa.",
         "Perdidos": "estaban activos y dejaron de estarlo (línea roja)."},
        "Si el crecimiento depende solo de nuevos y los recurrentes no suben, el problema es retención.")
    ga = R["growth"]

    fig = go.Figure()
    for col, color in [("Recurrentes", "#1f6fb2"), ("Reactivados", "#6baed6"), ("Nuevos", "#c6dbef")]:
        fig.add_trace(go.Bar(name=col, x=ga["eje"], y=ga[col], marker_color=color))
    fig.add_trace(go.Scatter(name="Perdidos", x=ga["eje"], y=-ga["Perdidos"],
                             line=dict(color=ROJO, width=2), mode="lines+markers"))
    fig.update_layout(barmode="stack", yaxis_title="Usuarios activos")
    show(fig, height=460)

    ga2 = ga.copy()
    ga2["% recurrentes"] = (ga2["Recurrentes"] / ga2["Total activos"] * 100).round(0)
    st.dataframe(ga2[["eje", "Nuevos", "Recurrentes", "Reactivados", "Total activos",
                      "Perdidos", "% recurrentes"]], use_container_width=True)

    if es_global:
        st.subheader("Por marca")
        gm = R["growth_marca"]
        fig2 = make_subplots(rows=2, cols=2, subplot_titles=list(gm.keys()))
        for (marca, g), (rr, cc) in zip(gm.items(), [(1, 1), (1, 2), (2, 1), (2, 2)]):
            for col, color in [("Recurrentes", "#1f6fb2"), ("Reactivados", "#6baed6"), ("Nuevos", "#c6dbef")]:
                fig2.add_trace(go.Bar(name=col, x=g["eje"], y=g[col], marker_color=color,
                                      showlegend=(rr == 1 and cc == 1)), row=rr, col=cc)
        fig2.update_layout(barmode="stack")
        show(fig2, height=620)


# ==================================================================
# ⑧ COHORTES
# ==================================================================
elif seccion == SECCIONES[7]:
    st.header("⑧ Retención por cohorte")
    st.caption(f"% de cada cohorte que sigue activo N periodos después · {etiqueta_marca}")
    glosario(
        "Cuánto aguanta cada 'generación' de usuarios según el mes en que se activó por primera vez.",
        "Se agrupa a los usuarios por su mes de primera actividad (cohorte) y se mide qué "
        "porcentaje sigue activo 1, 2, 3… periodos después. m0 siempre es 100%.",
        {"Cohorte": "todos los que se activaron por primera vez el mismo mes.",
         "+N": "N periodos después de la primera actividad.",
         "Acantilado": "la caída brusca típica del periodo +1."},
        "Ver si las mejoras de producto elevan la curva de las cohortes nuevas vs. las viejas.")
    coh = R["cohortes"]
    mcols = [c for c in coh.columns if c.startswith("m")]

    z = coh[mcols].values.astype(float) * 100
    fig = go.Figure(go.Heatmap(
        z=z, x=[f"+{i}" for i in range(len(mcols))],
        y=[f"{r.Cohorte} (n={int(r.n):,})" for r in coh.itertuples()],
        colorscale="YlGnBu", zmin=0, zmax=100,
        text=[[f"{v:.0f}" if not np.isnan(v) else "" for v in row] for row in z],
        texttemplate="%{text}", colorbar=dict(title="%")))
    fig.update_layout(yaxis=dict(autorange="reversed"),
                      xaxis_title="Periodos desde la primera actividad")
    show(fig, height=430)

    figc = go.Figure()
    for r in coh.itertuples():
        ys = [getattr(r, c) * 100 if not pd.isna(getattr(r, c)) else None for c in mcols]
        figc.add_trace(go.Scatter(x=list(range(len(mcols))), y=ys, mode="lines+markers",
                                  name=r.Cohorte))
    figc.update_layout(title="Curvas de vida", yaxis_title="% de la cohorte activo",
                       xaxis_title="Periodos desde la primera actividad")
    show(figc, height=420)


# ==================================================================
# ⑨ LIFT DE RETENCIÓN (métrica del análisis estratégico)
# ==================================================================
elif seccion == SECCIONES[8]:
    st.header("⑨ Lift de retención — ¿qué contenido hace que vuelvan?")
    st.caption(f"Métrica del análisis estratégico (observada vs. esperada) · {etiqueta_marca}")
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
         "Gateway": "curso con el que ARRANCAN los usuarios nuevos, y cuánto retiene."},
        "Empujar los cursos gancho en carruseles/ruta y revisar por qué los callejón no retienen.")

    lift = R["lift_estrategico"]
    if lift.empty:
        st.info("No hay suficientes datos (≥100 transiciones por curso) en esta selección.")
    else:
        st.metric("Base esperada de retorno (esta selección)", f"{R['base_ret']:.1f}%")
        n = st.slider("Nº de cursos por lado", 5, 15, 8)
        top_g = lift.head(n).iloc[::-1]
        top_c = lift.tail(n)
        c1, c2 = st.columns(2)
        figg = go.Figure(go.Bar(
            x=top_g["lift_pp"], y=top_g["Nombre de la LE"], orientation="h", marker_color=VERDE,
            text=[f"{v:+.1f}pp (obs {o:.0f}%, n={int(nn)})"
                  for v, o, nn in zip(top_g["lift_pp"], top_g["retencion_obs_pct"], top_g["n_usuario_transiciones"])],
            textposition="auto"))
        figg.update_layout(title="GANCHO — retienen por encima de la base", xaxis_title="Lift (pp)")
        with c1:
            show(figg, height=460)
        figc = go.Figure(go.Bar(
            x=top_c["lift_pp"], y=top_c["Nombre de la LE"], orientation="h", marker_color=ROJO,
            text=[f"{v:+.1f}pp (obs {o:.0f}%, n={int(nn)})"
                  for v, o, nn in zip(top_c["lift_pp"], top_c["retencion_obs_pct"], top_c["n_usuario_transiciones"])],
            textposition="auto"))
        figc.update_layout(title="CALLEJÓN — por debajo de la base", xaxis_title="Lift (pp)")
        with c2:
            show(figc, height=460)

        with st.expander("Ver ranking completo"):
            st.dataframe(lift, use_container_width=True)

        # ---- Gateway de usuarios nuevos ----
        st.subheader("🚪 Puerta de entrada (gateway de usuarios nuevos)")
        st.caption("Con qué curso arrancan los usuarios NUEVOS y su lift de retención.")
        gw = R["gateway"]
        if not gw.empty:
            gtop = gw.head(n).iloc[::-1]
            figw = go.Figure(go.Bar(
                x=gtop["lift_pp"], y=gtop["Nombre de la LE"], orientation="h", marker_color=AZUL,
                text=[f"{v:+.1f}pp (obs {o:.0f}%, n={int(nn)})"
                      for v, o, nn in zip(gtop["lift_pp"], gtop["retencion_obs_pct"], gtop["n"])],
                textposition="auto"))
            figw.update_layout(title="Mejores puertas de entrada (por lift)", xaxis_title="Lift (pp)")
            show(figw, height=440)
            with st.expander("Ver tabla de gateways"):
                st.dataframe(gw, use_container_width=True)

    with st.expander("¿En qué se diferencia del lift del deck (s2d)?"):
        st.markdown(
            "El deck usaba una base **por mes** y promediaba los lifts. Esta versión "
            "(la del análisis estratégico) usa una **base global única** y agrupa todas las "
            "transiciones — es más estable y comparable entre cursos. Aquí tienes ambas para referencia:")
        if not R["lift_deck"].empty:
            st.dataframe(R["lift_deck"].round(2), use_container_width=True)

st.sidebar.divider()
st.sidebar.caption("Definiciones (filtros, marcas, tramos, segmentos, growth, cohortes, "
                   "lift) replican el notebook oficial y el análisis estratégico.")
