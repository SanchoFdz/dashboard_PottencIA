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
import gc
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
COL_USU_RAW = "Nº Usuarios efectivos (RAW)"
COL_ACT = "Nº Usuarios activos (DISTINCT_COUNT)"

MESES_ES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
            "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10,
            "noviembre": 11, "diciembre": 12}
MES_ABR = {1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
           7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"}
MESES_ES_INV = {v: k.capitalize() for k, v in MESES_ES.items()}

# Columnas que se conservan de consumo_por_usuario. Las cinco ultimas se
# descartaban antes y son las que alimentan las secciones de certificacion,
# catalogo, formato y centro/nivel.
COLS_MIN = ["Usuario", "Nombre de la LE", "ID de la LE", "Tramo porcentaje",
            "Horas de aprendizaje", "Nº de contenidos consumidos",
            "Plantilla", "Nivel", "Certificado", "Centro", "Fecha de creación"]

# Umbrales de consumo por usuario y periodo (el KPI 2 del comite habla de
# minutos, no de horas: 20 min = 1/3 h).
UMBRAL_20MIN = 1.0 / 3.0

# Centro inferido del dominio del correo. El proveedor manda la columna
# "Centro" con ~0.6% de nulos, y el mapeo dominio -> centro es 1 a 1 en toda
# la base (ningun dominio aparece en dos centros), asi que el dominio rellena
# los nulos sin inventar nada.
DOMINIO_CENTRO = {
    "edu.utc.mx": "Universidad Tres Culturas",
    "doc.utc.mx": "Universidad Tres Culturas",
    "utc.mx": "Universidad Tres Culturas",
    "alumnos.uvt.edu.mx": "Universidad Tres Culturas",
    "my.ula.edu.mx": "Universidad Latinoamericana",
    "ula.edu.mx": "Universidad Latinoamericana",
    "lottus.com": "Universidad Latinoamericana",
    "lottuseducation.com": "Universidad Latinoamericana",
    "uane.mx": "Universidad Americana del Noreste",
    "uane.edu.mx": "Universidad Americana del Noreste",
    "alumnos.uteg.edu.mx": "Centro Universitario UTEG",
    "uteg.edu.mx": "Centro Universitario UTEG",
    "indo.edu.mx": "Colegio Indoamericano",
    "alumnos.emintermedica.mx": "Escuela de Medicina Intermedica",
    "doc.emintermedica.mx": "Escuela de Medicina Intermedica",
}

# Ruta de Master en IA: 18 LEs certificables (lista de Academia, sep-2026).
# El match con el catalogo se hace por nombre normalizado, no por ID, porque
# la lista llega en texto; hoy resuelve 18 de 18.
RUTA_MASTER = [
    "Bases y conceptos clave de la IA",
    "Fundamentos del Análisis de Datos",
    "Principios de data science",
    "Ética: Uso Responsable de Datos",
    "Impacto global de la IA",
    "Fundamentos de Machine Learning",
    "Lenguaje inteligente: cómo la IA está cambiando la comunicación",
    "De la Imagen a la Inteligencia: aplicaciones de la visión artificial",
    "Riesgos y Seguridad en la Inteligencia Artificial",
    "Metodologías ágiles con IA",
    "Gestión de proyectos con IA",
    "Aplicaciones Avanzadas y Ética en el Análisis de Datos Sociales",
    "Aplicaciones de data science",
    "Modelos Avanzados y Aplicaciones Prácticas de Machine Learning",
    "Gobernanza y Regulación de la Inteligencia Artificial",
    "Transformación organizacional y ventaja competitiva con IA",
    "Inteligencia de negocios basada en datos e IA",
    "Aplicaciones de redes neuronales",
]

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


def extraer_centro(u: str) -> str:
    """Centro a partir del dominio del correo (ver DOMINIO_CENTRO)."""
    dom = str(u).split("@")[-1].strip().lower()
    return DOMINIO_CENTRO.get(dom, "OTROS")


def limpiar_usuarios(df: pd.DataFrame) -> pd.DataFrame:
    df = df[~df["Usuario"].astype(str).str.contains(FILTRO_TEST, case=False, na=False)].copy()
    df["Universidad"] = df["Usuario"].apply(extraer_universidad)
    # El Centro se resuelve AQUI, mientras el correo todavia existe: en modo
    # preparado el Usuario se anonimiza y el dominio ya no seria recuperable.
    _dom = df["Usuario"].apply(extraer_centro)
    if "Centro" in df.columns:
        df["Centro"] = df["Centro"].fillna("").replace("", np.nan).fillna(_dom)
    else:
        df["Centro"] = _dom
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


# Columnas de texto con poquisimos valores distintos (4 a 120 sobre cientos de
# miles de filas). En object cada celda es un str de Python: el snapshot de
# Marzo pesaba 233 MB, 786 bytes por fila, y los 8 periodos juntos 1.19 GB.
# Streamlit Community Cloud corta en ~1 GB, asi que el proceso moria por OOM.
# Con category se guarda un codigo entero por fila y el diccionario una sola
# vez. Todos los groupby llevan observed=True, asi que la conversion no cambia
# ningun resultado (verificado con un digest completo de `computar`).
COLS_CATEGORIA = ("Usuario", "ID de la LE", "Nombre de la LE", "Tramo porcentaje",
                  "Universidad", "Plantilla", "Nivel", "Certificado", "Centro",
                  "Fecha de creación")


def _compactar(df: pd.DataFrame) -> pd.DataFrame:
    """Pasa a category las columnas de baja cardinalidad y encoge los numericos."""
    if df is None or df.empty:
        return df
    for c in COLS_CATEGORIA:
        if c not in df.columns:
            continue
        if df[c].dtype == object:
            df[c] = df[c].astype("category")
        if isinstance(df[c].dtype, pd.CategoricalDtype):
            # Orden de categorias SIEMPRE alfabetico. groupby(observed=True) ordena
            # los grupos por el orden de la categoria, y al leer con pyarrow ese
            # orden es el del diccionario interno del parquet: dejaba el orden de
            # las tablas a merced de como quedo escrito el archivo.
            cats = sorted(df[c].cat.categories)
            if list(df[c].cat.categories) != cats:
                df[c] = df[c].cat.reorder_categories(cats)
    for c in df.select_dtypes(include=["int64"]).columns:
        df[c] = pd.to_numeric(df[c], downcast="integer")
    # Los float NO se tocan: bajar a float32 cambiaba 2694.96 por 2694.959961 y
    # esas cifras van a la pantalla del comite. El ahorro eran 2 MB de 233.
    return df


def _leer_parquet(path: str) -> pd.DataFrame:
    """Lee un parquet ya en category, sin pasar por object.

    pd.read_parquet materializa cada celda como str de Python y recien despues
    podriamos compactar: ese pico transitorio (~230 MB por snapshot) es lo que
    disparaba el OOM, aunque el estado estable fuera pequenno. El parquet ya
    guarda estas columnas dictionary-encoded, asi que to_pandas(categories=...)
    construye la categoria directo desde el diccionario.
    """
    try:
        import pyarrow.parquet as pq
        tabla = pq.read_table(path)
        cats = [c for c in COLS_CATEGORIA if c in tabla.column_names]
        df = tabla.to_pandas(categories=cats)
        del tabla
        return _compactar(df)
    except ImportError:
        return _compactar(pd.read_parquet(path))



# ==================================================================
# CARGA CRUDA  (Sección 1 del notebook: current vs previous)
# ==================================================================
def _cargar_snapshots_prepared() -> dict:
    """Lee los frames ya limpios/slim en parquet (deployment)."""
    out = {}
    out["cpu_cur"] = _leer_parquet(os.path.join(PREPARED_DIR, "current", "snapshot.parquet"))
    out["cpu_prev"] = _leer_parquet(os.path.join(PREPARED_DIR, "previous", "snapshot.parquet"))
    for lado, path in [("cur", "current"), ("prev", "previous")]:
        out[f"horas_{lado}"] = pd.read_parquet(os.path.join(PREPARED_DIR, path, "horas.parquet"))
        out[f"consumo_mensual_{lado}"] = pd.read_parquet(os.path.join(PREPARED_DIR, path, "consumo.parquet"))
        out[f"usuarios_mensuales_{lado}"] = pd.read_parquet(os.path.join(PREPARED_DIR, path, "usuarios.parquet"))
        out[f"horas_{lado}"]["fecha"] = pd.to_datetime(out[f"horas_{lado}"]["fecha"], errors="coerce")
        out[f"consumo_mensual_{lado}"]["fecha"] = pd.to_datetime(out[f"consumo_mensual_{lado}"]["fecha"], errors="coerce")
        out[f"usuarios_mensuales_{lado}"]["fecha"] = pd.to_datetime(out[f"usuarios_mensuales_{lado}"]["fecha"], errors="coerce")
    for lado in ("cur", "prev"):
        u = out[f"usuarios_mensuales_{lado}"]
        if COL_USU_RAW not in u.columns:      # parquet anterior a esta version
            u[COL_USU_RAW] = u[COL_USU] * FACTOR_EFECTIVOS
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
    out["cpu_cur"] = _compactar(limpiar_usuarios(_load_latest(cur_path, "consumo_por_usuario__*.csv")))

    out["consumo_mensual_prev"] = _load_latest(prev_path, "Consumo_mensual_*.csv")
    out["usuarios_mensuales_prev"] = _load_latest(prev_path, "Usuarios_mensuales_*.csv")
    out["horas_prev"] = _load_latest(prev_path, "Horas_de_aprendizaje_*.csv")
    out["cpu_prev"] = _compactar(limpiar_usuarios(_load_latest(prev_path, "consumo_por_usuario__*.csv")))

    for k in ["horas_cur", "horas_prev", "consumo_mensual_cur", "consumo_mensual_prev",
              "usuarios_mensuales_cur", "usuarios_mensuales_prev"]:
        if "fecha" in out[k].columns:
            out[k]["fecha"] = pd.to_datetime(out[k]["fecha"], errors="coerce")

    # Corrección doble conteo de usuarios efectivos (serie diaria).
    # Se conserva el valor SIN dividir: la razon efectivos/activos que reporta
    # el portal solo tiene sentido con los dos valores crudos (ver seccion
    # "Embudo" y el glosario del taller de KPIs).
    for k in ["usuarios_mensuales_cur", "usuarios_mensuales_prev"]:
        out[k][COL_USU_RAW] = out[k][COL_USU]
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
    uh = df.groupby("Usuario", as_index=False, observed=True)["Horas de aprendizaje"].sum()
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



def _avance(serie: pd.Series) -> pd.Series:
    """Tramo de texto -> numero (10/35/65/90).

    Siempre numerico: si "Tramo porcentaje" viene como category, .map() devuelve
    otra category y un .max() sobre ella truena con "Cannot perform max with
    non-ordered Categorical".
    """
    return pd.to_numeric(serie.map(TRAMO_MAP), errors="coerce")


def abandono(df_cpu: pd.DataFrame) -> dict:
    """SLIDE 4: distribución de máximo avance (tramo) por (Usuario, LE)."""
    d = df_cpu.copy()
    d["avance"] = _avance(d["Tramo porcentaje"])
    agg = (d.groupby(["Usuario", "ID de la LE"], as_index=False, observed=True)
           .agg({"avance": "max"}).dropna())
    dist = agg["avance"].value_counts(normalize=True).sort_index()
    return {
        "detalle": agg,
        "dist_tramos": dist,
        "pct_bajo20": float((agg["avance"] < 20).mean()),
        "pct_alto80": float((agg["avance"] >= 80).mean()),
    }



def _descat(df: pd.DataFrame) -> pd.DataFrame:
    """Devuelve las columnas category a texto plano.

    Se usa en los frames YA agregados (decenas de filas, no cientos de miles),
    donde el ahorro de category es nulo y en cambio estorba: un merge externo
    deja NaN en la clave y un fillna posterior truena con "Cannot setitem on a
    Categorical with a new category".
    """
    out = df.copy()
    for c in out.columns:
        if isinstance(out[c].dtype, pd.CategoricalDtype):
            out[c] = out[c].astype(object)
    return out


def top_les(d: dict, n: int = 5) -> dict:
    """SLIDE 5: Top/Bottom LEs por horas y por variación mes vs mes."""
    def horas_le(df):
        return (df.groupby(["ID de la LE", "Nombre de la LE"], as_index=False, observed=True)
                ["Horas de aprendizaje"].sum())
    cur = _descat(horas_le(d["cpu_cur"]).rename(columns={"Horas de aprendizaje": "horas_cur"}))
    prev = _descat(horas_le(d["cpu_prev"]).rename(columns={"Horas de aprendizaje": "horas_prev"}))
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
                             "df": _leer_parquet(f)})
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
                         "df": _compactar(_cargar_snapshot_hist(f))})
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
        g = (p["df"].groupby("Usuario", observed=True)
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
        g = (dd.groupby(["ID de la LE", "Nombre de la LE"], observed=True)["Usuario"]
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
    lift_le = (lift.groupby(["ID de la LE", "Nombre de la LE"], observed=True)
               .apply(lambda g: pd.Series({
                   "n_total": g["n"].sum(),
                   "retorno_medio": np.average(g["retorno"], weights=g["n"]),
                   "lift_pp": np.average(g["lift_pp"], weights=g["n"])}),
                      include_groups=False)
               .reset_index()
               .query("n_total >= @MIN_CONS_LE")
               .sort_values(["lift_pp", "n_total", "ID de la LE"],
                            ascending=[False, False, True]))
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
        g = act.groupby(["ID de la LE", "Nombre de la LE"], observed=True)["Usuario"].apply(set)
        d = {}
        for (idle, nom), s in g.items():
            d[idle] = s
            name_map[idle] = nom
        activos_le[p["orden"]] = d

    # sorted(): iterar el set directamente hacia el orden de hash de Python, que
    # cambia entre corridas. Con empates en lift_pp el ranking de gancho/callejon
    # salia distinto sin que cambiara ni un dato.
    todas = sorted(set().union(*[set(activos_le[o]) for o in ordenes])) if ordenes else []
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
    # Desempate explicito: a igual lift manda la LE con mas transiciones (mas
    # evidencia) y, si tambien empatan, el ID. Sin esto el orden entre empates lo
    # decidia el quicksort y el ranking bailaba entre corridas.
    lift = (pd.DataFrame(rows)
            .sort_values(["lift_pp", "n_usuario_transiciones", "ID de la LE"],
                         ascending=[False, False, True]).reset_index(drop=True)
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
        top = sub.groupby("Usuario", as_index=False, observed=True).first()
        for _, r in top.iterrows():
            le = r["ID de la LE"]
            name_map[le] = r["Nombre de la LE"]
            inicio[le]["den"] += 1
            if r["Usuario"] in apm[mt1]:
                inicio[le]["num"] += 1
        visto |= set(act["Usuario"].unique())
    rows = []
    for le in sorted(inicio):
        d = inicio[le]
        if d["den"] >= 100:
            obs = 100 * d["num"] / d["den"]
            rows.append({"ID de la LE": le, "Nombre de la LE": name_map[le], "n": d["den"],
                         "retencion_obs_pct": round(obs, 1), "lift_pp": round(obs - base, 1)})
    return (pd.DataFrame(rows)
            .sort_values(["lift_pp", "n", "ID de la LE"], ascending=[False, False, True])
            .reset_index(drop=True)
            if rows else pd.DataFrame(columns=["ID de la LE", "Nombre de la LE", "n",
                                               "retencion_obs_pct", "lift_pp"]))


# ==================================================================
# BLOQUE NUEVO (sep-2026): metricas que el deck no tenia
#   Todas salen de columnas que ya venian en los CSV del proveedor y que el
#   pipeline descartaba (Plantilla, Nivel, Certificado, Centro, Fecha de
#   creacion) o de la exportacion "Listado de usuarios" (roster).
#   Regla transversal: donde hay una distribucion se reportan MEDIA Y MEDIANA.
#   La media de horas por usuario esta dominada por la cola (el top 5% de
#   usuarios concentra la mitad de las horas), asi que sola miente.
# ==================================================================
def _norm_nombre(s: str) -> str:
    """Normaliza nombres de LE para casar listas de texto con el catalogo."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]", " ", t)
    

def _norm_espacios(s: str) -> str:
    return re.sub(r"\s+", " ", _norm_nombre(s)).strip()


def cargar_roster() -> pd.DataFrame | None:
    """Base de usuarios con licencia (`Listado_de_usuarios__*.csv`).

    Es un acumulado de vida, no de la ventana de 30 dias: sirve como
    DENOMINADOR (cuanta gente tiene acceso) y para el corte por Centro y
    Nivel, nunca para sumar horas contra el snapshot del periodo.
    Devuelve None si la exportacion no esta disponible.
    """
    if USE_PREPARED:
        f = os.path.join(PREPARED_DIR, "roster.parquet")
        return _leer_parquet(f) if os.path.exists(f) else None
    for carpeta in (os.path.join(ROOT, "Nueva data"), CUR_PATH, HIST_DIR):
        files = glob.glob(os.path.join(carpeta, "Listado_de_usuarios*.csv"))
        if files:
            df = pd.read_csv(max(files, key=os.path.getmtime))
            df = limpiar_usuarios(df)
            df = df.rename(columns={"Curso": "Nivel",
                                    "Contenidos consumidos": "Nº de contenidos consumidos"})
            df["Nivel"] = df["Nivel"].astype(str).str.strip().str.lower().map(
                {"superior": "Superior", "mediosuperior": "Medio superior",
                 "medio superior": "Medio superior", "mediasuperior": "Medio superior",
                 "mediosuperior,superior": "Mixto", "licenciatura": "Superior",
                 "licenciatura udg": "Superior", "bachillerato udg": "Medio superior"}
            ).fillna("Sin dato")
            return df
    return None


def distribucion_horas(df_cpu: pd.DataFrame) -> dict:
    """Media Y mediana de horas por usuario, mas concentracion de la cola.

    El deck reportaba solo el promedio. Con una distribucion tan sesgada, la
    media describe al top 5% y la mediana al alumno real; el comite necesita
    las dos para no fijar metas sobre el numero equivocado.
    """
    uh = df_cpu.groupby("Usuario", observed=True)["Horas de aprendizaje"].sum().sort_values(ascending=False)
    act = uh[uh > 0]
    n, tot = len(uh), float(uh.sum())

    def share(p):
        if not n or tot <= 0:
            return np.nan
        k = max(1, int(round(n * p)))
        return float(uh.head(k).sum() / tot * 100)

    def q(s, v):
        return float(s.quantile(v)) if len(s) else np.nan

    return {
        "n_usuarios": n, "n_activados": int(len(act)),
        "pct_activados": float(len(act) / n * 100) if n else np.nan,
        "horas_total": tot,
        "media_todos": float(uh.mean()) if n else np.nan,
        "mediana_todos": float(uh.median()) if n else np.nan,
        "media_act": float(act.mean()) if len(act) else np.nan,
        "mediana_act": float(act.median()) if len(act) else np.nan,
        "p25_act": q(act, 0.25), "p75_act": q(act, 0.75), "p90_act": q(act, 0.90),
        "share_top1": share(0.01), "share_top5": share(0.05), "share_top10": share(0.10),
        "pct_ge20min": float((act >= UMBRAL_20MIN).mean() * 100) if len(act) else np.nan,
        "pct_ge1h": float((act >= 1).mean() * 100) if len(act) else np.nan,
        "n_ge20min": int((act >= UMBRAL_20MIN).sum()),
        "serie_activados": act,
    }


def embudo_usuarios(df_cpu: pd.DataFrame, roster: pd.DataFrame | None = None,
                    marcas=None) -> pd.DataFrame:
    """Embudo de usuarios UNICOS: licencia -> inscrito -> efectivo -> profundidad.

    Los "activos" y "efectivos" de la serie diaria son sumas de conteos
    diarios (usuario-dia), no personas distintas, asi que no pueden entrar en
    un embudo de personas. Este se construye entero sobre usuarios unicos del
    snapshot mas el roster como denominador.
    """
    uh = df_cpu.groupby("Usuario", observed=True)["Horas de aprendizaje"].sum()
    filas = []
    if roster is not None and not roster.empty:
        r = _filtrar_marca(roster, marcas)
        filas.append(("Usuarios con licencia", int(r["Usuario"].nunique()),
                      "roster acumulado (Listado de usuarios)"))
    filas += [
        ("Inscritos a alguna LE en el periodo", int(len(uh)), "snapshot usuario x LE"),
        ("Efectivos: consumo > 0 h", int((uh > 0).sum()), "snapshot usuario x LE"),
        ("Con 20 min o más", int((uh >= UMBRAL_20MIN).sum()), "snapshot usuario x LE"),
        ("Con 1 h o más", int((uh >= 1).sum()), "snapshot usuario x LE"),
        ("Con 5 h o más", int((uh >= 5).sum()), "snapshot usuario x LE"),
    ]
    out = pd.DataFrame(filas, columns=["etapa", "usuarios", "fuente"])
    base = out["usuarios"].iloc[0]
    out["pct_base"] = out["usuarios"] / base * 100 if base else np.nan
    out["pct_paso"] = out["usuarios"] / out["usuarios"].shift(1) * 100
    return out


def activos_vs_efectivos(d: dict) -> dict:
    """Razon efectivos/activos de la serie diaria del portal (usuario-dia).

    Definicion del proveedor: activo = entro a la plataforma; efectivo = tuvo
    alguna actividad. Se calcula sobre los valores CRUDOS: la correccion /2 que
    el deck aplica a los efectivos rompe la razon (la dejaria en ~0.4 por
    construccion) y esa razon es justo la pregunta de negocio.
    """
    out = {}
    for lado in ("cur", "prev"):
        u = d[f"usuarios_mensuales_{lado}"]
        act = float(u[COL_ACT].sum())
        efe = float(u[COL_USU_RAW].sum()) if COL_USU_RAW in u.columns else float(u[COL_USU].sum()) * FACTOR_EFECTIVOS
        out[lado] = {
            "activos_ud": act, "efectivos_ud": efe,
            "ratio": efe / act * 100 if act else np.nan,
            "activos_dia_media": float(u[COL_ACT].mean()),
            "activos_dia_mediana": float(u[COL_ACT].median()),
            "efectivos_dia_media": efe / len(u) if len(u) else np.nan,
            "efectivos_dia_mediana": float(u[COL_USU_RAW].median()) if COL_USU_RAW in u.columns else np.nan,
            "dias": int(len(u)),
        }
    return out


def certificacion(df_cpu: pd.DataFrame) -> dict:
    """Certificados obtenidos: la unica metrica de RESULTADO del tablero.

    Ojo con la semantica: `Certificado` NO es un atributo del curso (99 de 112
    LEs tienen filas Si y No), es si ESE usuario obtuvo el certificado en ESE
    curso. Por eso es un resultado (correlaciona con llegar al 80-100%), no una
    palanca: no se puede "poner mas certificados" y esperar mas horas.
    """
    d = df_cpu.copy()
    d["cert"] = d["Certificado"].astype(str).str.strip().str.lower().eq("si")
    d["avance"] = _avance(d["Tramo porcentaje"])
    pares, n_cert = len(d), int(d["cert"].sum())
    usuarios = int(d["Usuario"].nunique())
    por_usuario = d[d["cert"]].groupby("Usuario", observed=True).size()
    fin = d[d["avance"] >= 90]
    # Bandera de calidad de dato: certificado con avance declarado bajo 20%.
    incoherentes = int(((d["cert"]) & (d["avance"] < 20)).sum())
    horas_cert = float(d[d["cert"]]["Horas de aprendizaje"].sum())
    return {
        "pares": pares, "certificados": n_cert,
        "tasa_par": n_cert / pares * 100 if pares else np.nan,
        "usuarios": usuarios,
        "usuarios_con_cert": int(len(por_usuario)),
        "tasa_usuario": len(por_usuario) / usuarios * 100 if usuarios else np.nan,
        "cert_por_usuario_media": float(por_usuario.mean()) if len(por_usuario) else np.nan,
        "cert_por_usuario_mediana": float(por_usuario.median()) if len(por_usuario) else np.nan,
        "pares_fin": int(len(fin)),
        # Entre los pares que SI llegan al tramo 80-100%, cuantos traen
        # certificado. Se cuenta sobre `fin`, no sobre el total de
        # certificados: hay certificados declarados con avance bajo 20% (ver
        # `incoherentes`) y usar el total daba tasas sobre 100%.
        "tasa_cert_entre_fin": float(fin["cert"].mean() * 100) if len(fin) else np.nan,
        "incoherentes": incoherentes,
        "pct_horas_en_cert": horas_cert / float(d["Horas de aprendizaje"].sum()) * 100
                             if float(d["Horas de aprendizaje"].sum()) else np.nan,
        "serie_por_usuario": por_usuario,
    }


def certificacion_por_periodo(periodos: list, marcas=None) -> pd.DataFrame:
    """Evolucion mes a mes de certificados y tasa de certificacion."""
    filas = []
    for p in periodos:
        df = _filtrar_marca(p["df"], marcas)
        if "Certificado" not in df.columns:
            continue
        c = certificacion(df)
        filas.append({"eje": p["eje"], "label": p["label"],
                      "Certificados": c["certificados"],
                      "Usuarios con certificado": c["usuarios_con_cert"],
                      "Tasa por usuario (%)": round(c["tasa_usuario"], 1),
                      "Tasa por inscripcion (%)": round(c["tasa_par"], 2)})
    return pd.DataFrame(filas)


def certificacion_por_grupo(df_cpu: pd.DataFrame, col: str) -> pd.DataFrame:
    """Certificados por marca / centro / nivel, con media y mediana por usuario."""
    d = df_cpu.copy()
    d["cert"] = d["Certificado"].astype(str).str.strip().str.lower().eq("si")
    filas = []
    for g, sub in d.groupby(col, observed=True):
        c = certificacion(sub)
        filas.append({col: g, "Usuarios": c["usuarios"],
                      "Certificados": c["certificados"],
                      "Usuarios con certificado": c["usuarios_con_cert"],
                      "Tasa por usuario (%)": round(c["tasa_usuario"], 1),
                      "Cert. por usuario (media)": round(c["cert_por_usuario_media"], 2)
                      if pd.notna(c["cert_por_usuario_media"]) else np.nan,
                      "Cert. por usuario (mediana)": c["cert_por_usuario_mediana"]})
    return pd.DataFrame(filas).sort_values("Certificados", ascending=False)


def catalogo_les(df_cpu: pd.DataFrame, df_prev: pd.DataFrame | None = None,
                 umbral_dormida: float = 1.0) -> dict:
    """Catalogo por LE con su FECHA DE CREACION: uso vs antiguedad.

    La fecha sale de la propia columna del snapshot, asi que funciona para
    cualquier fecha de creacion sin listas fijas: cada mes que el proveedor
    publique LEs nuevas entran solas.
    """
    d = df_cpu.copy()
    d["avance"] = _avance(d["Tramo porcentaje"])
    d["cert"] = d["Certificado"].astype(str).str.strip().str.lower().eq("si")
    g = (d.groupby(["ID de la LE", "Nombre de la LE"], as_index=False, observed=True)
         .agg(horas=("Horas de aprendizaje", "sum"),
              inscripciones=("Usuario", "size"),
              usuarios=("Usuario", "nunique"),
              certificados=("cert", "sum"),
              avance_medio=("avance", "mean"),
              avance_mediana=("avance", "median"),
              plantilla=("Plantilla", "first"),
              creada=("Fecha de creación", "first")))
    # g son ~100 filas: aqui category no ahorra nada y rompe to_datetime y .max()
    g = _descat(g)
    g["creada"] = pd.to_datetime(g["creada"], errors="coerce")
    g["horas_por_usuario"] = g["horas"] / g["usuarios"].replace(0, np.nan)
    ref = g["creada"].max()
    g["edad_dias"] = (ref - g["creada"]).dt.days
    g["dormida"] = g["horas"] < umbral_dormida
    if df_prev is not None and not df_prev.empty:
        pv = (df_prev.groupby("ID de la LE", as_index=False, observed=True)["Horas de aprendizaje"]
              .sum().rename(columns={"Horas de aprendizaje": "horas_prev"}))
        g = g.merge(pv, on="ID de la LE", how="left")
        g["horas_prev"] = g["horas_prev"].fillna(0.0)
        g["delta"] = g["horas"] - g["horas_prev"]
    g = g.sort_values("horas", ascending=False).reset_index(drop=True)

    cohortes = (g.dropna(subset=["creada"]).assign(mes=lambda x: x["creada"].dt.to_period("M"))
                .groupby("mes", as_index=False, observed=True)
                .agg(les=("ID de la LE", "size"), horas=("horas", "sum"),
                     usuarios=("usuarios", "sum"), dormidas=("dormida", "sum")))
    cohortes["mes_ts"] = cohortes["mes"].dt.to_timestamp()
    cohortes["horas_por_le"] = cohortes["horas"] / cohortes["les"]
    tot = float(g["horas"].sum())
    return {
        "les": g, "cohortes_creacion": cohortes,
        "n_les": int(len(g)), "n_dormidas": int(g["dormida"].sum()),
        "horas_total": tot,
        "share_top5": float(g["horas"].head(5).sum() / tot * 100) if tot else np.nan,
        "share_top10": float(g["horas"].head(10).sum() / tot * 100) if tot else np.nan,
        "horas_por_le_media": float(g["horas"].mean()) if len(g) else np.nan,
        "horas_por_le_mediana": float(g["horas"].median()) if len(g) else np.nan,
    }


def formato_plantilla(df_cpu: pd.DataFrame) -> pd.DataFrame:
    """Rendimiento por formato de curso (`Plantilla`): horas por inscripcion."""
    d = df_cpu.copy()
    d["avance"] = _avance(d["Tramo porcentaje"])
    pares = (d.dropna(subset=["avance"])
             .groupby(["Usuario", "ID de la LE", "Plantilla"], as_index=False, observed=True)["avance"].max())
    av = pares.groupby("Plantilla", observed=True)["avance"].agg(
        bajo20=lambda s: (s < 20).mean() * 100, alto80=lambda s: (s >= 80).mean() * 100)
    g = (d.groupby("Plantilla", as_index=False, observed=True)
         .agg(horas=("Horas de aprendizaje", "sum"),
              inscripciones=("Usuario", "size"),
              usuarios=("Usuario", "nunique"),
              les=("ID de la LE", "nunique")))
    g["h_por_inscripcion_media"] = g["horas"] / g["inscripciones"]
    med = (d.groupby(["Plantilla", "Usuario"], observed=True)["Horas de aprendizaje"].sum()
           .groupby("Plantilla", observed=True).median().rename("h_por_usuario_mediana").reset_index())
    g = g.merge(med, on="Plantilla", how="left").merge(av, on="Plantilla", how="left")
    return g.sort_values("horas", ascending=False).reset_index(drop=True)


def por_centro_nivel(df_cpu: pd.DataFrame, roster: pd.DataFrame | None = None,
                     col: str = "Centro") -> pd.DataFrame:
    """Corte por Centro (inferido del correo) o Nivel, con media y mediana."""
    d = df_cpu.copy()
    d["cert"] = d["Certificado"].astype(str).str.strip().str.lower().eq("si")
    uh = d.groupby([col, "Usuario"], as_index=False, observed=True)["Horas de aprendizaje"].sum()
    g = (uh.groupby(col, as_index=False, observed=True)
         .agg(usuarios=("Usuario", "nunique"),
              horas=("Horas de aprendizaje", "sum"),
              media=("Horas de aprendizaje", "mean"),
              mediana=("Horas de aprendizaje", "median")))
    act = (uh[uh["Horas de aprendizaje"] > 0].groupby(col, observed=True)["Usuario"].nunique()
           .rename("activados").reset_index())
    g = g.merge(act, on=col, how="left")
    g["activados"] = g["activados"].fillna(0).astype(int)
    g["pct_activados"] = g["activados"] / g["usuarios"] * 100
    med_act = (uh[uh["Horas de aprendizaje"] > 0].groupby(col, observed=True)["Horas de aprendizaje"]
               .agg(media_act="mean", mediana_act="median").reset_index())
    g = g.merge(med_act, on=col, how="left")
    cert = d[d["cert"]].groupby(col, observed=True)["Usuario"].nunique().rename("usuarios_con_cert").reset_index()
    g = g.merge(cert, on=col, how="left")
    g["usuarios_con_cert"] = g["usuarios_con_cert"].fillna(0).astype(int)
    if roster is not None and col in roster.columns:
        lic = roster.groupby(col, observed=True)["Usuario"].nunique().rename("licencias").reset_index()
        g = g.merge(lic, on=col, how="left")
        g["pct_licencia_inscrita"] = g["usuarios"] / g["licencias"] * 100
        g["pct_licencia_efectiva"] = g["activados"] / g["licencias"] * 100
    return g.sort_values("horas", ascending=False).reset_index(drop=True)


def ruta_master(df_cpu: pd.DataFrame, nombres=None) -> dict:
    """Ruta de Master en IA: avance por curso y cobertura por alumno."""
    nombres = list(nombres or RUTA_MASTER)
    objetivo = {_norm_espacios(n): n for n in nombres}
    d = df_cpu.copy()
    d["_n"] = d["Nombre de la LE"].map(_norm_espacios)
    # match exacto por nombre normalizado y, si no, por prefijo (el catalogo
    # antepone "MS - " a algunos titulos de la ruta).
    def _match(n):
        if n in objetivo:
            return objetivo[n]
        for k, v in objetivo.items():
            if k and (n.endswith(k) or k in n):
                return v
        return None
    d["curso_ruta"] = d["_n"].map(_match)
    en_ruta = d[d["curso_ruta"].notna()].copy()
    en_ruta["avance"] = _avance(en_ruta["Tramo porcentaje"])
    en_ruta["cert"] = en_ruta["Certificado"].astype(str).str.strip().str.lower().eq("si")

    por_curso = (en_ruta.groupby("curso_ruta", as_index=False, observed=True)
                 .agg(usuarios=("Usuario", "nunique"),
                      horas=("Horas de aprendizaje", "sum"),
                      certificados=("cert", "sum"),
                      avance_medio=("avance", "mean"),
                      avance_mediana=("avance", "median")))
    por_curso["completado_pct"] = [
        float((en_ruta[(en_ruta["curso_ruta"] == c)]
               .groupby("Usuario", observed=True)["avance"].max() >= 90).mean() * 100)
        for c in por_curso["curso_ruta"]]
    por_curso["orden"] = por_curso["curso_ruta"].map({n: i for i, n in enumerate(nombres)})
    por_curso = por_curso.sort_values("orden").reset_index(drop=True)

    avance_u = en_ruta.groupby(["Usuario", "curso_ruta"], observed=True)["avance"].max().reset_index()
    # "Tocar" un curso es CONSUMIRLO, no estar inscrito en el. La mayoria de los
    # alumnos aparece inscrita en los 18 cursos de la ruta (asignacion masiva),
    # asi que contar filas mide el reparto del administrador, no al alumno.
    con_consumo = en_ruta[en_ruta["Horas de aprendizaje"] > 0]
    cobertura = (con_consumo.groupby("Usuario", observed=True)["curso_ruta"].nunique()
                 .reindex(en_ruta["Usuario"].unique()).fillna(0).astype(int))
    inscritos_u = en_ruta.groupby("Usuario", observed=True)["curso_ruta"].nunique()
    completos = (avance_u[avance_u["avance"] >= 90].groupby("Usuario", observed=True)["curso_ruta"]
                 .nunique().reindex(cobertura.index).fillna(0))
    horas_u = en_ruta.groupby("Usuario", observed=True)["Horas de aprendizaje"].sum()
    return {
        "por_curso": por_curso,
        "n_cursos_ruta": len(nombres),
        "n_cursos_encontrados": int(por_curso["curso_ruta"].nunique()),
        "no_encontrados": [n for n in nombres if n not in set(por_curso["curso_ruta"])],
        "usuarios": int(cobertura.size),
        "cobertura_media": float(cobertura.mean()) if cobertura.size else np.nan,
        "cobertura_mediana": float(cobertura.median()) if cobertura.size else np.nan,
        "completos_media": float(completos.mean()) if completos.size else np.nan,
        "completos_mediana": float(completos.median()) if completos.size else np.nan,
        "ruta_terminada": int((completos >= len(nombres)).sum()),
        "horas_media": float(horas_u.mean()) if horas_u.size else np.nan,
        "horas_mediana": float(horas_u.median()) if horas_u.size else np.nan,
        "horas_total": float(horas_u.sum()),
        "dist_cobertura": cobertura.value_counts().sort_index(),
        "inscritos_media": float(inscritos_u.mean()) if inscritos_u.size else np.nan,
        "inscritos_mediana": float(inscritos_u.median()) if inscritos_u.size else np.nan,
        "usuarios_con_consumo": int((cobertura > 0).sum()),
        "dist_completos": completos.value_counts().sort_index(),
        "pct_horas_plataforma": float(horas_u.sum() /
                                      float(df_cpu["Horas de aprendizaje"].sum()) * 100)
                                if float(df_cpu["Horas de aprendizaje"].sum()) else np.nan,
    }


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
    # La lectura de los 8 snapshots deja bastante basura transitoria. En local da
    # igual; en Streamlit Community Cloud el limite de RAM es lo que tumbo la app.
    gc.collect()
    return {
        "d": d,
        "roster": cargar_roster(),
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
    roster = base.get("roster")
    roster_f = _filtrar_marca(roster, marcas) if roster is not None else None

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
        # ---- Bloque nuevo (sep-2026) ----
        "dist_cur": distribucion_horas(cpu_cur),
        "dist_prev": distribucion_horas(cpu_prev),
        "embudo": embudo_usuarios(cpu_cur, roster, marcas),
        "embudo_prev": embudo_usuarios(cpu_prev, roster, marcas),
        "act_vs_efe": activos_vs_efectivos(d),
        "cert_cur": certificacion(cpu_cur),
        "cert_prev": certificacion(cpu_prev),
        "cert_periodo": certificacion_por_periodo(periodos, marcas),
        "cert_marca": certificacion_por_grupo(d["cpu_cur"], "Universidad"),
        "catalogo": catalogo_les(cpu_cur, cpu_prev),
        "formato": formato_plantilla(cpu_cur),
        "centro": por_centro_nivel(cpu_cur, roster_f, "Centro"),
        "nivel": por_centro_nivel(cpu_cur, roster_f, "Nivel"),
        "ruta": ruta_master(cpu_cur),
        "ruta_prev": ruta_master(cpu_prev),
        "roster": roster_f,
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
