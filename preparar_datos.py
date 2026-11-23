"""
preparar_datos.py: Empaqueta los CSV crudos del proveedor en parquet slim.

Convierte ~380 MB de CSV (mnt/data/current, previous y datos_analisis_estrategico_2026)
en unos pocos MB de parquet dentro de `dashboard/data/`, para que el repo sea
autocontenido y desplegable en Streamlit Cloud sin subir los CSV pesados.

Modo calendario (desde nov-2026): si existe `Pottencia Year/month_to_month/`, los
periodos son meses calendario (un snapshot por carpeta <mes>_<aa>) y las series
diarias salen de `Pottencia Year/`. Actual = ultimo mes completo, anterior = el
previo. Para actualizar: anadir la carpeta del mes nuevo y reemplazar las 4
series diarias del export anual, y volver a correr este script.

Uso (flujo semanal de Santiago, modo ventanas):
    1. Descarga y coloca los CSV nuevos en mnt/data/{current,previous} (y el snapshot
       mensual en datos_analisis_estrategico_2026 al cerrar mes).
    2. Ejecuta:  python dashboard/preparar_datos.py
    3. git add dashboard/data && git commit && git push  →  Streamlit Cloud redepliega.

La transformación reutiliza EXACTAMENTE los loaders del pipeline en modo CSV, así que
los parquet contienen los mismos datos limpios (filtro test, marca, ÷2 efectivos).
"""

import os
import json
import shutil
import hashlib

import pandas as pd


def _hash_usuario(serie: pd.Series) -> pd.Series:
    """Anonimiza el correo del alumno a un ID opaco estable (misma persona → mismo ID).
    Preserva intersecciones/cohortes; la marca ya vive en su propia columna."""
    return serie.astype(str).map(lambda u: "u_" + hashlib.sha1(u.encode()).hexdigest()[:16])

# Forzar modo CSV aunque ya exista dashboard/data (para poder re-preparar)
import pipeline as pl
pl.USE_PREPARED = False

OUT = pl.PREPARED_DIR
COMPRESSION = "zstd"

COLS_SLIM = ["Usuario", "ID de la LE", "Nombre de la LE", "Tramo porcentaje",
             "Horas de aprendizaje", "Nº de contenidos consumidos", "Universidad",
             # columnas que antes se tiraban y alimentan certificacion,
             # catalogo, formato y centro/nivel
             "Plantilla", "Nivel", "Certificado", "Centro", "Fecha de creación",
             "Poblacion"]

COLS_ROSTER = ["Usuario", "Universidad", "Centro", "Nivel", "Poblacion",
               "Horas de aprendizaje", "Nº de contenidos consumidos",
               "Experiencias activas"]


def _dump(df, path, cols=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if cols:
        df = df[[c for c in cols if c in df.columns]].copy()
    if "Usuario" in df.columns:            # anonimiza PII antes de escribir a disco/repo
        df["Usuario"] = _hash_usuario(df["Usuario"])
    df.to_parquet(path, compression=COMPRESSION, index=False)
    print(f"  ✓ {os.path.relpath(path, OUT)}  ({len(df):,} filas, "
          f"{os.path.getsize(path)/1e6:.2f} MB)")


def main():
    print("Leyendo CSV crudos (modo desarrollo)…")
    # Se lee TODO antes de borrar data/: si falta un CSV, el parquet anterior
    # queda intacto (antes se borraba primero y habia que restaurarlo con git).
    d = pl.cargar_snapshots_mensuales()
    periodos = pl.construir_periodos(d)          # hist + prev/cur
    roster = pl.cargar_roster()
    calendario = d.get("modo") == "calendario"
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)

    print("Escribiendo parquet slim en dashboard/data/ …")
    # current / previous
    for lado, path in [("cur", "current"), ("prev", "previous")]:
        _dump(d[f"cpu_{lado}"], os.path.join(OUT, path, "snapshot.parquet"), COLS_SLIM)
        _dump(d[f"horas_{lado}"], os.path.join(OUT, path, "horas.parquet"))
        _dump(d[f"consumo_mensual_{lado}"], os.path.join(OUT, path, "consumo.parquet"))
        # usuarios: ya viene ÷2 desde cargar_snapshots_mensuales
        _dump(d[f"usuarios_mensuales_{lado}"], os.path.join(OUT, path, "usuarios.parquet"))

    # histórico: solo los meses que no son actual/anterior (esos se reconstruyen
    # desde current/previous y no se duplican en el repo)
    if calendario:
        omitir = {d["orden_cur"], d["orden_prev"]}
        es_cp = lambda p: p["orden"] in omitir
    else:
        cur_prev_labels = {f"Prev ({d['prev_label']})", f"Actual ({d['cur_label']})"}
        es_cp = lambda p: p["label"] in cur_prev_labels
    for p in periodos:
        if es_cp(p):
            continue
        _dump(p["df"], os.path.join(OUT, "historico", f"snapshot_{p['orden']:02d}.parquet"), COLS_SLIM)

    if calendario:
        meta = {"modo": "calendario", "orden_cur": int(d["orden_cur"]),
                "orden_prev": int(d["orden_prev"]),
                "parciales": [int(o) for o in d.get("parciales", [])]}
        json.dump(meta, open(os.path.join(OUT, "meta.json"), "w"), indent=1)
        print(f"  ✓ meta.json  {meta}")

    # roster de licencias (denominador del embudo)
    if roster is not None:
        _dump(roster, os.path.join(OUT, "roster.parquet"), COLS_ROSTER)
    else:
        print("  ! sin Listado_de_usuarios: el embudo se queda sin denominador de licencias")

    # serie diaria larga histórica (raw, sin prev/cur; el pipeline los re-anexa)
    hist_serie = (d["serie_anual_horas"] if calendario
                  else pl._load_latest(pl.HIST_DIR, "Horas_de_aprendizaje_*.csv"))
    _dump(hist_serie, os.path.join(OUT, "historico", "serie_larga_horas.parquet"))

    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _, fs in os.walk(OUT) for f in fs)
    print(f"\n✅ Listo. dashboard/data/ = {total/1e6:.2f} MB total.")
    print("   Ahora: git add dashboard/data && git commit && git push")


if __name__ == "__main__":
    main()
