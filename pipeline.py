"""
pipeline.py: Motor de datos del Dashboard PottencIA / ODILO.

Replica, celda por celda, la lógica del notebook `consumo_contenidos_3.ipynb`
que genera el deck mensual del comité (carpeta outputs/deck_mensual/<fecha>/).
Las definiciones canónicas (filtros, marcas, tramos, segmentos, growth accounting,
cohortes, lift) son IDÉNTICAS a las del notebook para que el dashboard produzca
exactamente los mismos números que las presentaciones históricas.

Fuentes de datos (lo que Santiago descarga del proveedor Odilo BI):
  - mnt/data/current/    : snapshot del mes en curso  (Horas_, Usuarios_, Consumo_,
                           consumo_por_usuario__*.csv)
  - mnt/data/previous/   : snapshot del mes anterior (mismo esquema)
  - datos_analisis_estrategico_2026/ : histórico
        * consumo_por_usuario__<mes>.csv  (un snapshot por mes calendario)
        * Horas_de_aprendizaje_*.csv       (serie diaria larga sin huecos)

Para refrescar semanalmente: reemplazar los CSV en esas carpetas (mover el
current viejo a previous) y pulsar «Recargar datos» en el dashboard.
"""

from __future__ import annotations

import os
import re
import glob
import datetime as dt
from collections import defaultdict

import numpy as np
import pandas as pd

# ------------------------------------------------------------------
# Rutas (relativas a la raíz del repo ODILO, un nivel sobre dashboard/)
# ------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))

CUR_PATH = os.path.join(ROOT, "mnt", "data", "current")
PREV_PATH = os.path.join(ROOT, "mnt", "data", "previous")
HIST_DIR = os.path.join(ROOT, "datos_analisis_estrategico_2026")

# Modo "preparado": si existe dashboard/data/ (parquet slim), la app lo usa
# (deployment autocontenido en Streamlit Cloud). Si no, lee los CSV crudos del
# proveedor en el layout ODILO (desarrollo local). Ver preparar_datos.py.
PREPARED_DIR = os.path.join(HERE, "data")
USE_PREPARED = os.path.isdir(PREPARED_DIR)

# ------------------------------------------------------------------
# Definiciones canónicas del comité (idénticas al notebook)
# ------------------------------------------------------------------
FILTRO_TEST = "test|@ula.edu.mx|prueba"
MARCAS_MAP = [("uane", "UANE"), ("ula", "ULA"), ("utc", "UTC"),
              ("uteg", "UTEG"), ("indo", "INDO")]
MARCAS_4 = ["UANE", "UTC", "ULA", "UTEG"]
TRAMO_MAP = {"Entre 0% y 20%": 10, "Entre 20% y 50%": 35,
             "Entre 50% y 80%": 65, "Entre 80% y 100%": 90}
# "Corrección doble conteo" heredada del deck v2 (ver FABLE-5-MAP §2.2b).
FACTOR_EFECTIVOS = 2
MIN_CONS_LE = 40   # consumidores mínimos de una LE para entrar al ranking gancho/callejón

COL_USU = "Nº Usuarios efectivos (DISTINCT_COUNT)"
COL_ACT = "Nº Usuarios activos (DISTINCT_COUNT)"

MESES_ES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
            "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10,
            "noviembre": 11, "diciembre": 12}
MES_ABR = {1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
           7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"}
MESES_ES_INV = {v: k.capitalize() for k, v in MESES_ES.items()}

COLS_MIN = ["Usuario", "Nombre de la LE", "ID de la LE", "Tramo porcentaje",
            "Horas de aprendizaje", "Nº de contenidos consumidos"]

SEG_ORDER = ["Exploradores", "Constantes", "Intensivos", "Power users"]


# ------------------------------------------------------------------
# Helpers de limpieza (idénticos al notebook)
# ------------------------------------------------------------------
def extraer_universidad(u: str) -> str:
    u = str(u).lower()
    for key, name in MARCAS_MAP:
        if key in u:
            return name
    return "OTRAS"


def limpiar_usuarios(df: pd.DataFrame) -> pd.DataFrame:
    df = df[~df["Usuario"].astype(str).str.contains(FILTRO_TEST, case=False, na=False)].copy()
    df["Universidad"] = df["Usuario"].apply(extraer_universidad)
    return df


def segmentar_horas(h: float) -> str:
    if h == 0:
        return "No activados"
    elif h <= 1:
        return "Exploradores"
    elif h <= 5:
        return "Constantes"
    elif h <= 20:
        return "Intensivos"
    return "Power users"


def mom_change(cur, prev):
    if prev == 0 or pd.isna(prev):
        return np.nan
    return (cur - prev) / prev * 100.0


def _load_latest(folder: str, pattern: str) -> pd.DataFrame:
    files = glob.glob(os.path.join(folder, pattern))
    if not files:
        raise FileNotFoundError(f"No se encontró '{pattern}' en {folder}")
    f = max(files, key=os.path.getmtime)
    return pd.read_csv(f)


def _fmt_rango(serie_fecha: pd.Series) -> str:
    f = pd.to_datetime(serie_fecha, errors="coerce").dropna()
    if f.empty:
        return "s/d"
    return f"{f.min():%d-%b} → {f.max():%d-%b}"


# ==================================================================
# CARGA CRUDA  (Sección 1 del notebook: current vs previous)
# ==================================================================
def _cargar_snapshots_prepared() -> dict:
    """Lee los frames ya limpios/slim en parquet (deployment)."""
    out = {}
    out["cpu_cur"] = pd.read_parquet(os.path.join(PREPARED_DIR, "current", "snapshot.parquet"))
    out["cpu_prev"] = pd.read_parquet(os.path.join(PREPARED_DIR, "previous", "snapshot.parquet"))
    for lado, path in [("cur", "current"), ("prev", "previous")]:
        out[f"horas_{lado}"] = pd.read_parquet(os.path.join(PREPARED_DIR, path, "horas.parquet"))
        out[f"consumo_mensual_{lado}"] = pd.read_parquet(os.path.join(PREPARED_DIR, path, "consumo.parquet"))
        out[f"usuarios_mensuales_{lado}"] = pd.read_parquet(os.path.join(PREPARED_DIR, path, "usuarios.parquet"))
        out[f"horas_{lado}"]["fecha"] = pd.to_datetime(out[f"horas_{lado}"]["fecha"], errors="coerce")
        out[f"consumo_mensual_{lado}"]["fecha"] = pd.to_datetime(out[f"consumo_mensual_{lado}"]["fecha"], errors="coerce")
        out[f"usuarios_mensuales_{lado}"]["fecha"] = pd.to_datetime(out[f"usuarios_mensuales_{lado}"]["fecha"], errors="coerce")
    # usuarios efectivos YA vienen corregidos (÷2) desde preparar_datos → no re-dividir
    out["cur_label"] = _fmt_rango(out["horas_cur"]["fecha"])
    out["prev_label"] = _fmt_rango(out["horas_prev"]["fecha"])
    return out


def cargar_snapshots_mensuales(cur_path=CUR_PATH, prev_path=PREV_PATH) -> dict:
    """Devuelve todos los objetos que necesita la Sección 1 (mes actual vs anterior)."""
    if USE_PREPARED:
        return _cargar_snapshots_prepared()
    out = {}
    out["consumo_mensual_cur"] = _load_latest(cur_path, "Consumo_mensual_*.csv")
    out["usuarios_mensuales_cur"] = _load_latest(cur_path, "Usuarios_mensuales_*.csv")
    out["horas_cur"] = _load_latest(cur_path, "Horas_de_aprendizaje_*.csv")
    out["cpu_cur"] = limpiar_usuarios(_load_latest(cur_path, "consumo_por_usuario__*.csv"))

    out["consumo_mensual_prev"] = _load_latest(prev_path, "Consumo_mensual_*.csv")
    out["usuarios_mensuales_prev"] = _load_latest(prev_path, "Usuarios_mensuales_*.csv")
    out["horas_prev"] = _load_latest(prev_path, "Horas_de_aprendizaje_*.csv")
    out["cpu_prev"] = limpiar_usuarios(_load_latest(prev_path, "consumo_por_usuario__*.csv"))

    for k in ["horas_cur", "horas_prev", "consumo_mensual_cur", "consumo_mensual_prev",
              "usuarios_mensuales_cur", "usuarios_mensuales_prev"]:
        if "fecha" in out[k].columns:
            out[k]["fecha"] = pd.to_datetime(out[k]["fecha"], errors="coerce")

    # Corrección doble conteo de usuarios efectivos (serie diaria)
    for k in ["usuarios_mensuales_cur", "usuarios_mensuales_prev"]:
        out[k][COL_USU] = out[k][COL_USU] / FACTOR_EFECTIVOS

    out["cur_label"] = _fmt_rango(out["horas_cur"]["fecha"])
    out["prev_label"] = _fmt_rango(out["horas_prev"]["fecha"])
    return out


def panorama_kpis(d: dict) -> pd.DataFrame:
    """SLIDE 1: 4 KPIs globales, actual vs anterior (fuente: serie diaria de plataforma)."""
    filas = [
        ("Horas consumidas",
         d["horas_cur"]["Horas de aprendizaje (SUM)"].sum(),
         d["horas_prev"]["Horas de aprendizaje (SUM)"].sum()),
        ("Contenidos únicos",
         d["consumo_mensual_cur"]["cadenarecurso (DISTINCT_COUNT)"].sum(),
         d["consumo_mensual_prev"]["cadenarecurso (DISTINCT_COUNT)"].sum()),
        ("Usuarios activos",
         d["usuarios_mensuales_cur"][COL_ACT].sum(),
         d["usuarios_mensuales_prev"][COL_ACT].sum()),
        ("Usuarios efectivos",
         d["usuarios_mensuales_cur"][COL_USU].sum(),
         d["usuarios_mensuales_prev"][COL_USU].sum()),
    ]
    df = pd.DataFrame(filas, columns=["kpi", "actual", "anterior"])
    df["delta_pct"] = df.apply(lambda r: mom_change(r["actual"], r["anterior"]), axis=1)
    return df


def panorama_por_marca(d: dict) -> pd.DataFrame:
    rows = []
    for marca in MARCAS_4:
        cur_m = d["cpu_cur"][d["cpu_cur"]["Universidad"] == marca]
        prev_m = d["cpu_prev"][d["cpu_prev"]["Universidad"] == marca]
        rows.append({
            "Universidad": marca,
            "Horas_actual": float(cur_m["Horas de aprendizaje"].sum()),
            "Horas_anterior": float(prev_m["Horas de aprendizaje"].sum()),
            "Contenidos_actual": float(cur_m["Nº de contenidos consumidos"].sum()),
            "Contenidos_anterior": float(prev_m["Nº de contenidos consumidos"].sum()),
            "Usuarios_actual": int(cur_m["Usuario"].nunique()),
            "Usuarios_anterior": int(prev_m["Usuario"].nunique()),
        })
    return pd.DataFrame(rows)


def tendencias_diarias(d: dict) -> dict:
    """SLIDE 2: serie diaria del mes actual (rolling 7d) vs promedio del mes anterior."""
    h = d["horas_cur"].sort_values("fecha").copy()
    c = d["consumo_mensual_cur"].sort_values("fecha").copy()
    h["rolling_7d"] = h["Horas de aprendizaje (SUM)"].rolling(7, min_periods=1).mean()
    c["rolling_7d"] = c["cadenarecurso (DISTINCT_COUNT)"].rolling(7, min_periods=1).mean()
    return {
        "horas": h[["fecha", "Horas de aprendizaje (SUM)", "rolling_7d"]],
        "contenidos": c[["fecha", "cadenarecurso (DISTINCT_COUNT)", "rolling_7d"]],
        "horas_prev_avg": d["horas_prev"]["Horas de aprendizaje (SUM)"].mean(),
        "contenidos_prev_avg": d["consumo_mensual_prev"]["cadenarecurso (DISTINCT_COUNT)"].mean(),
    }


def _horas_por_usuario(df: pd.DataFrame) -> pd.DataFrame:
    uh = df.groupby("Usuario", as_index=False)["Horas de aprendizaje"].sum()
    uh["segmento"] = uh["Horas de aprendizaje"].apply(segmentar_horas)
    return uh


def segmentacion(df_cpu: pd.DataFrame) -> dict:
    """SLIDE 3: activación (No activados vs Activados) e intensidad (4 segmentos)."""
    uh = _horas_por_usuario(df_cpu)
    activacion = (uh["segmento"]
                  .replace({s: "Activados" for s in SEG_ORDER})
                  .value_counts(normalize=True)
                  .reindex(["No activados", "Activados"]).fillna(0))
    intensidad = (uh[uh["segmento"] != "No activados"]["segmento"]
                  .value_counts(normalize=True)
                  .reindex(SEG_ORDER).fillna(0))
    conteo = uh["segmento"].value_counts().reindex(["No activados"] + SEG_ORDER).fillna(0).astype(int)
    return {"activacion": activacion, "intensidad": intensidad, "conteo": conteo}


def segmentacion_por_marca(d: dict) -> pd.DataFrame:
    rows = []
    for marca in MARCAS_4:
        cur_m = d["cpu_cur"][d["cpu_cur"]["Universidad"] == marca]
        if cur_m.empty:
            continue
        seg = segmentacion(cur_m)
        row = {"Universidad": marca, "n_usuarios": int(cur_m["Usuario"].nunique())}
        row["No activados"] = float(seg["activacion"].get("No activados", 0))
        row["Activados"] = float(seg["activacion"].get("Activados", 0))
        for s in SEG_ORDER:
            row[s] = float(seg["intensidad"].get(s, 0))
        rows.append(row)
    return pd.DataFrame(rows)


def abandono(df_cpu: pd.DataFrame) -> dict:
    """SLIDE 4: distribución de máximo avance (tramo) por (Usuario, LE)."""
    d = df_cpu.copy()
    d["avance"] = d["Tramo porcentaje"].map(TRAMO_MAP)
    agg = (d.groupby(["Usuario", "ID de la LE"], as_index=False)
           .agg({"avance": "max"}).dropna())
    dist = agg["avance"].value_counts(normalize=True).sort_index()
    return {
        "detalle": agg,
        "dist_tramos": dist,
        "pct_bajo20": float((agg["avance"] < 20).mean()),
        "pct_alto80": float((agg["avance"] >= 80).mean()),
    }


def top_les(d: dict, n: int = 5) -> dict:
    """SLIDE 5: Top/Bottom LEs por horas y por variación mes vs mes."""
    def horas_le(df):
        return (df.groupby(["ID de la LE", "Nombre de la LE"], as_index=False)
                ["Horas de aprendizaje"].sum())
    cur = horas_le(d["cpu_cur"]).rename(columns={"Horas de aprendizaje": "horas_cur"})
    prev = horas_le(d["cpu_prev"]).rename(columns={"Horas de aprendizaje": "horas_prev"})
    m = cur.merge(prev[["ID de la LE", "horas_prev"]], on="ID de la LE", how="outer").fillna(0)
    # nombre puede faltar si sólo aparecía en prev
    m["horas_cur"] = m["horas_cur"].astype(float)
    m["horas_prev"] = m["horas_prev"].astype(float)
    m["delta"] = m["horas_cur"] - m["horas_prev"]
    top_horas = m.sort_values("horas_cur", ascending=False).head(n)
    top_mejora = m[m["horas_prev"] >= 1].sort_values("delta", ascending=False).head(n)
    bottom_caida = m[m["horas_prev"] >= 1].sort_values("delta").head(n)
    return {"top_horas": top_horas, "top_mejora": top_mejora, "bottom_caida": bottom_caida}


# ==================================================================
# SECCIÓN 2 : estratégica (histórico largo)
# ==================================================================
def _cargar_snapshot_hist(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=lambda c: c in COLS_MIN)
    return limpiar_usuarios(df)


def construir_periodos(d: dict, hist_dir=HIST_DIR) -> list:
    """Panel de periodos: snapshots calendario del histórico + previous + current."""
    periodos = []
    if USE_PREPARED:
        for f in sorted(glob.glob(os.path.join(PREPARED_DIR, "historico", "snapshot_*.parquet"))):
            orden = int(re.search(r"snapshot_(\d+)\.parquet", f).group(1))
            periodos.append({"orden": orden, "label": MESES_ES_INV.get(orden, MES_ABR[orden]),
                             "df": pd.read_parquet(f)})
    else:
        periodos = _construir_periodos_hist_csv(hist_dir)
    return _cerrar_periodos(periodos, d)


def _construir_periodos_hist_csv(hist_dir):
    periodos = []
    for f in sorted(glob.glob(os.path.join(hist_dir, "consumo_por_usuario__*.csv"))):
        m = re.search(r"__([a-záéíóú]+)\.csv", f, flags=re.I)
        if not m:
            continue
        mes = m.group(1).lower()
        if mes not in MESES_ES:
            continue
        periodos.append({"orden": MESES_ES[mes], "label": mes.capitalize(),
                         "df": _cargar_snapshot_hist(f)})
    return periodos


def _cerrar_periodos(periodos, d):
    """Añade previous/current (etiquetados por el punto medio de su ventana) y ordena."""
    def _mes_medio(horas_df):
        f = pd.to_datetime(horas_df["fecha"], errors="coerce").dropna()
        return int((f.min() + (f.max() - f.min()) / 2).month)

    prev_mes = _mes_medio(d["horas_prev"])
    cur_mes = _mes_medio(d["horas_cur"])
    periodos.append({"orden": prev_mes, "label": f"Prev ({d['prev_label']})",
                     "df": d["cpu_prev"]})
    periodos.append({"orden": cur_mes, "label": f"Actual ({d['cur_label']})",
                     "df": d["cpu_cur"]})
    periodos = sorted(periodos, key=lambda p: p["orden"])
    for p in periodos:
        p["eje"] = MES_ABR[p["orden"]]
    return periodos


def panel_usuario_mes(periodos: list) -> pd.DataFrame:
    filas = []
    for p in periodos:
        g = (p["df"].groupby("Usuario")
             .agg(horas=("Horas de aprendizaje", "sum"),
                  Universidad=("Universidad", "first")).reset_index())
        g["orden"] = p["orden"]
        g["eje"] = p["eje"]
        filas.append(g)
    panel = pd.concat(filas, ignore_index=True)
    panel["activo"] = panel["horas"] > 0
    return panel


def _activos_por_mes(panel, ordenes):
    return {o: set(panel[(panel["orden"] == o) & panel["activo"]]["Usuario"]) for o in ordenes}


def growth_accounting(panel: pd.DataFrame, ordenes: list, marca_de: dict | None = None) -> pd.DataFrame:
    apm = _activos_por_mes(panel, ordenes)
    if marca_de is not None:
        apm = {o: {u for u in apm[o] if marca_de.get(u) is not None} for o in ordenes}
    first_seen = {}
    for o in ordenes:
        for u in apm[o]:
            first_seen.setdefault(u, o)
    rows = []
    prev = set()
    for o in ordenes:
        cur = apm[o]
        nuevos = {u for u in cur if first_seen[u] == o}
        recur = cur & prev
        react = (cur - prev) - nuevos
        perdidos = prev - cur
        rows.append({"orden": o, "eje": MES_ABR[o], "Nuevos": len(nuevos),
                     "Recurrentes": len(recur), "Reactivados": len(react),
                     "Total activos": len(cur), "Perdidos": len(perdidos)})
        prev = cur
    return pd.DataFrame(rows)


def growth_accounting_marca(panel, ordenes) -> dict:
    marca_de = panel.drop_duplicates("Usuario").set_index("Usuario")["Universidad"].to_dict()
    out = {}
    for marca in MARCAS_4:
        md = {u: marca for u, m in marca_de.items() if m == marca}
        out[marca] = growth_accounting(panel, ordenes, marca_de=md)
    return out


def cohortes_retencion(panel, ordenes) -> pd.DataFrame:
    apm = _activos_por_mes(panel, ordenes)
    first_seen = {}
    for o in ordenes:
        for u in apm[o]:
            first_seen.setdefault(u, o)
    cohortes = {}
    for u, o in first_seen.items():
        cohortes.setdefault(o, set()).add(u)
    mat = []
    for c in ordenes:
        size = len(cohortes.get(c, set()))
        fila = {"Cohorte": MES_ABR[c], "n": size}
        for k, o in enumerate(ordenes):
            if o < c:
                continue
            kk = ordenes.index(o) - ordenes.index(c)
            ret = len(cohortes.get(c, set()) & apm[o]) / size if size else np.nan
            fila[f"m{kk}"] = ret
        mat.append(fila)
    return pd.DataFrame(mat)


def lift_les(periodos: list, panel: pd.DataFrame, ordenes: list) -> pd.DataFrame:
    apm = _activos_por_mes(panel, ordenes)
    cons_le = []
    for p in periodos:
        dd = p["df"]
        dd = dd[dd["Horas de aprendizaje"] > 0]
        g = (dd.groupby(["ID de la LE", "Nombre de la LE"])["Usuario"]
             .apply(set).reset_index().rename(columns={"Usuario": "users"}))
        g["orden"] = p["orden"]
        cons_le.append(g)
    cons_le = pd.concat(cons_le, ignore_index=True)

    base_ret = {}
    for i, o in enumerate(ordenes[:-1]):
        o2 = ordenes[i + 1]
        a = apm[o]
        base_ret[o] = len(a & apm[o2]) / len(a) if a else np.nan

    orden_pos = {o: i for i, o in enumerate(ordenes)}
    registros = []
    for _, row in cons_le.iterrows():
        o = row["orden"]
        if o == ordenes[-1]:
            continue
        o2 = ordenes[orden_pos[o] + 1]
        users = row["users"]
        if len(users) < MIN_CONS_LE:
            continue
        ret = len(users & apm[o2]) / len(users)
        registros.append({"ID de la LE": row["ID de la LE"], "Nombre de la LE": row["Nombre de la LE"],
                          "orden": o, "n": len(users), "retorno": ret, "base": base_ret[o],
                          "lift_pp": (ret - base_ret[o]) * 100})
    lift = pd.DataFrame(registros)
    if lift.empty:
        return lift
    lift_le = (lift.groupby(["ID de la LE", "Nombre de la LE"])
               .apply(lambda g: pd.Series({
                   "n_total": g["n"].sum(),
                   "retorno_medio": np.average(g["retorno"], weights=g["n"]),
                   "lift_pp": np.average(g["lift_pp"], weights=g["n"])}),
                      include_groups=False)
               .reset_index()
               .query("n_total >= @MIN_CONS_LE")
               .sort_values("lift_pp", ascending=False))
    return lift_le


def serie_diaria_larga(d: dict, hist_serie=None) -> pd.DataFrame:
    """SLIDE 2A: serie diaria larga (histórico) + previous + current, con rolling y estacional."""
    if hist_serie is None:
        if USE_PREPARED:
            hist_serie = pd.read_parquet(os.path.join(PREPARED_DIR, "historico", "serie_larga_horas.parquet"))
        else:
            hist_serie = _load_latest(HIST_DIR, "Horas_de_aprendizaje_*.csv")
    serie = hist_serie.copy()
    serie["fecha"] = pd.to_datetime(serie["fecha"], errors="coerce")
    serie = serie.rename(columns={"Horas de aprendizaje (SUM)": "horas"})[["fecha", "horas"]]
    for extra in [d["horas_prev"], d["horas_cur"]]:
        e = extra.rename(columns={"Horas de aprendizaje (SUM)": "horas"})[["fecha", "horas"]].copy()
        e["fecha"] = pd.to_datetime(e["fecha"], errors="coerce")
        serie = pd.concat([serie, e[["fecha", "horas"]]], ignore_index=True)
    serie = (serie.dropna(subset=["fecha"]).sort_values("fecha")
             .drop_duplicates(subset="fecha", keep="last").reset_index(drop=True))
    serie["r7"] = serie["horas"].rolling(7, min_periods=1).mean()
    serie["r28"] = serie["horas"].rolling(28, min_periods=7, center=True).mean()
    serie["idx_estacional"] = serie["horas"] / serie["r28"]
    return serie


# ==================================================================
# ORQUESTADOR
# ==================================================================
def cargar_todo(cur_path=CUR_PATH, prev_path=PREV_PATH, hist_dir=HIST_DIR) -> dict:
    """Calcula TODAS las tablas del deck. Devuelve un dict listo para la UI."""
    d = cargar_snapshots_mensuales(cur_path, prev_path)
    periodos = construir_periodos(d, hist_dir)
    ordenes = [p["orden"] for p in periodos]
    panel = panel_usuario_mes(periodos)

    res = {
        "meta": {
            "cur_label": d["cur_label"],
            "prev_label": d["prev_label"],
            "generado": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "ejes": [p["eje"] for p in periodos],
        },
        # Sección 1
        "panorama": panorama_kpis(d),
        "panorama_marca": panorama_por_marca(d),
        "tendencias": tendencias_diarias(d),
        "segmentacion_global": segmentacion(d["cpu_cur"]),
        "segmentacion_marca": segmentacion_por_marca(d),
        "abandono_cur": abandono(d["cpu_cur"]),
        "abandono_prev": abandono(d["cpu_prev"]),
        "top_les": top_les(d),
        # Sección 2
        "panel": panel,
        "growth": growth_accounting(panel, ordenes),
        "growth_marca": growth_accounting_marca(panel, ordenes),
        "cohortes": cohortes_retencion(panel, ordenes),
        "lift": lift_les(periodos, panel, ordenes),
        "serie_larga": serie_diaria_larga(d),
    }
    return res


# ==================================================================
# LIFT "ESTRATÉGICO" (versión del análisis estratégico que prefiere Santiago)
#   Réplica de analisis_rutas_grafo.lift_retencion / gateway_nuevos.
#   Diferencia con el lift del deck (s2d): la retención ESPERADA es la
#   tasa base GLOBAL de todas las transiciones t→t+1 (un solo número), y el
#   observado se agrupa (pool) sobre TODOS los meses, no promedio ponderado.
#   lift_pp = retención_observada − retención_esperada.
# ==================================================================
def _filtrar_marca(df: pd.DataFrame, marcas) -> pd.DataFrame:
    if not marcas:
        return df
    return df[df["Universidad"].isin(marcas)]


def lift_estrategico(periodos: list, panel: pd.DataFrame, ordenes: list, marcas=None):
    """Devuelve (df_lift, base_global_pct). Réplica exacta del análisis estratégico."""
    panel_f = _filtrar_marca(panel, marcas)
    apm = _activos_por_mes(panel_f, ordenes)

    # Retención base global sobre TODAS las transiciones t→t+1
    ret_num = ret_den = 0
    for t in range(len(ordenes) - 1):
        a_t, a_t1 = apm[ordenes[t]], apm[ordenes[t + 1]]
        ret_num += len(a_t & a_t1)
        ret_den += len(a_t)
    base = 100 * ret_num / ret_den if ret_den else 0.0

    # activos por LE en cada mes
    activos_le = {}
    name_map = {}
    for p in periodos:
        df = _filtrar_marca(p["df"], marcas)
        act = df[df["Horas de aprendizaje"] > 0]
        g = act.groupby(["ID de la LE", "Nombre de la LE"])["Usuario"].apply(set)
        d = {}
        for (idle, nom), s in g.items():
            d[idle] = s
            name_map[idle] = nom
        activos_le[p["orden"]] = d

    todas = set().union(*[set(activos_le[o]) for o in ordenes]) if ordenes else set()
    rows = []
    for le in todas:
        num = den = 0
        for t in range(len(ordenes) - 1):
            usu = activos_le[ordenes[t]].get(le, set())
            den += len(usu)
            num += len(usu & apm[ordenes[t + 1]])
        if den >= 100:  # umbral de muestra (igual que el script original)
            obs = 100 * num / den
            rows.append({"ID de la LE": le, "Nombre de la LE": name_map[le],
                         "n_usuario_transiciones": den,
                         "retencion_obs_pct": round(obs, 1),
                         "retencion_esperada_pct": round(base, 1),
                         "lift_pp": round(obs - base, 1)})
    lift = (pd.DataFrame(rows).sort_values("lift_pp", ascending=False).reset_index(drop=True)
            if rows else pd.DataFrame(columns=["ID de la LE", "Nombre de la LE",
                                               "n_usuario_transiciones", "retencion_obs_pct",
                                               "retencion_esperada_pct", "lift_pp"]))
    return lift, base


def gateway_estrategico(periodos: list, panel: pd.DataFrame, ordenes: list, base: float, marcas=None):
    """LEs 'puerta de entrada': con qué LE arrancan los usuarios NUEVOS y su lift."""
    panel_f = _filtrar_marca(panel, marcas)
    apm = _activos_por_mes(panel_f, ordenes)
    data = {p["orden"]: _filtrar_marca(p["df"], marcas) for p in periodos}

    visto = set()
    inicio = defaultdict(lambda: {"num": 0, "den": 0})
    name_map = {}
    for t in range(len(ordenes) - 1):
        mt, mt1 = ordenes[t], ordenes[t + 1]
        act = data[mt][data[mt]["Horas de aprendizaje"] > 0]
        nuevos = set(act["Usuario"].unique()) - visto
        sub = act[act["Usuario"].isin(nuevos)].sort_values(
            ["Usuario", "Horas de aprendizaje"], ascending=[True, False])
        top = sub.groupby("Usuario", as_index=False).first()
        for _, r in top.iterrows():
            le = r["ID de la LE"]
            name_map[le] = r["Nombre de la LE"]
            inicio[le]["den"] += 1
            if r["Usuario"] in apm[mt1]:
                inicio[le]["num"] += 1
        visto |= set(act["Usuario"].unique())
    rows = []
    for le, d in inicio.items():
        if d["den"] >= 100:
            obs = 100 * d["num"] / d["den"]
            rows.append({"ID de la LE": le, "Nombre de la LE": name_map[le], "n": d["den"],
                         "retencion_obs_pct": round(obs, 1), "lift_pp": round(obs - base, 1)})
    return (pd.DataFrame(rows).sort_values("lift_pp", ascending=False).reset_index(drop=True)
            if rows else pd.DataFrame(columns=["ID de la LE", "Nombre de la LE", "n",
                                               "retencion_obs_pct", "lift_pp"]))


# ==================================================================
# BASE cacheable + orquestador con filtro de marca (para el dashboard)
# ==================================================================
def cargar_base(cur_path=CUR_PATH, prev_path=PREV_PATH, hist_dir=HIST_DIR) -> dict:
    """
    Carga y limpia TODO lo pesado UNA sola vez (para cachear en Streamlit).
    Devuelve los frames crudos + estructuras derivadas globales. El filtrado por
    marca y los agregados por sección se calculan después (rápido) con `computar`.
    """
    d = cargar_snapshots_mensuales(cur_path, prev_path)
    periodos = construir_periodos(d, hist_dir)
    ordenes = [p["orden"] for p in periodos]
    panel = panel_usuario_mes(periodos)
    marcas = [m for m in MARCAS_4 if (panel["Universidad"] == m).any()]
    return {
        "d": d,
        "periodos": periodos,
        "ordenes": ordenes,
        "panel": panel,
        "serie_larga": serie_diaria_larga(d),
        "marcas": marcas,
        "meta": {
            "cur_label": d["cur_label"],
            "prev_label": d["prev_label"],
            "generado": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "ejes": [p["eje"] for p in periodos],
        },
    }


def computar(base: dict, marcas=None) -> dict:
    """Calcula los agregados de cada sección para la selección de marcas dada."""
    d = base["d"]
    periodos = base["periodos"]
    ordenes = base["ordenes"]
    panel = base["panel"]

    cpu_cur = _filtrar_marca(d["cpu_cur"], marcas)
    cpu_prev = _filtrar_marca(d["cpu_prev"], marcas)
    panel_f = _filtrar_marca(panel, marcas)

    lift_e, base_ret = lift_estrategico(periodos, panel, ordenes, marcas)
    d_marca = {"cpu_cur": cpu_cur, "cpu_prev": cpu_prev}

    return {
        "meta": base["meta"],
        "marcas_sel": marcas or base["marcas"],
        # Sección 1 (marca-aware salvo KPIs de serie diaria)
        "panorama": panorama_kpis(d),               # global (serie diaria, sin marca)
        "panorama_marca": panorama_por_marca(d),    # ya es por marca
        "tendencias": tendencias_diarias(d),        # global (serie diaria)
        "segmentacion_global": segmentacion(cpu_cur),
        "segmentacion_marca": segmentacion_por_marca(d),
        "abandono_cur": abandono(cpu_cur),
        "abandono_prev": abandono(cpu_prev),
        "top_les": top_les(d_marca),
        # Sección 2 (marca-aware)
        "growth": growth_accounting(panel_f, ordenes),
        "growth_marca": growth_accounting_marca(panel, ordenes),
        "cohortes": cohortes_retencion(panel_f, ordenes),
        "lift_deck": lift_les(_filtrar_periodos(periodos, marcas), panel_f, ordenes),
        "lift_estrategico": lift_e,
        "gateway": gateway_estrategico(periodos, panel, ordenes, base_ret, marcas),
        "base_ret": base_ret,
        "serie_larga": base["serie_larga"],
    }


def _filtrar_periodos(periodos, marcas):
    if not marcas:
        return periodos
    return [{**p, "df": _filtrar_marca(p["df"], marcas)} for p in periodos]


if __name__ == "__main__":
    # Smoke test: imprime formas de todas las tablas.
    b = cargar_base()
    le, base = lift_estrategico(b["periodos"], b["panel"], b["ordenes"])
    print("LIFT ESTRATÉGICO (global) base=%.1f%%" % base)
    print(le.head(6).to_string(index=False))
    print("\nGATEWAY:")
    print(gateway_estrategico(b["periodos"], b["panel"], b["ordenes"], base).head(6).to_string(index=False))
    r = cargar_todo()
    print("META:", r["meta"])
    print("panorama:\n", r["panorama"])
    print("growth:\n", r["growth"])
    print("cohortes:\n", r["cohortes"].round(2))
    print("lift shape:", r["lift"].shape)
    print("serie_larga:", r["serie_larga"].shape)
