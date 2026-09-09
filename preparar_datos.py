"""
preparar_datos.py: Empaqueta los CSV crudos del proveedor en parquet slim.

Convierte ~380 MB de CSV (mnt/data/current, previous y datos_analisis_estrategico_2026)
en unos pocos MB de parquet dentro de `dashboard/data/`, para que el repo sea
autocontenido y desplegable en Streamlit Cloud sin subir los CSV pesados.

Uso (flujo semanal de Santiago):
    1. Descarga y coloca los CSV nuevos en mnt/data/{current,previous} (y el snapshot
       mensual en datos_analisis_estrategico_2026 al cerrar mes).
    2. Ejecuta:  python dashboard/preparar_datos.py
    3. git add dashboard/data && git commit && git push  →  Streamlit Cloud redepliega.

La transformación reutiliza EXACTAMENTE los loaders del pipeline en modo CSV, así que
los parquet contienen los mismos datos limpios (filtro test, marca, ÷2 efectivos).
"""

import os
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
             "Horas de aprendizaje", "Nº de contenidos consumidos", "Universidad"]


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
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    print("Leyendo CSV crudos (modo desarrollo)…")
    d = pl.cargar_snapshots_mensuales()
    periodos = pl.construir_periodos(d)          # hist + prev/cur
    serie = pl.serie_diaria_larga(d)             # ya incluye prev/cur

    print("Escribiendo parquet slim en dashboard/data/ …")
    # current / previous
    for lado, path in [("cur", "current"), ("prev", "previous")]:
        _dump(d[f"cpu_{lado}"], os.path.join(OUT, path, "snapshot.parquet"), COLS_SLIM)
        _dump(d[f"horas_{lado}"], os.path.join(OUT, path, "horas.parquet"))
        _dump(d[f"consumo_mensual_{lado}"], os.path.join(OUT, path, "consumo.parquet"))
        # usuarios: ya viene ÷2 desde cargar_snapshots_mensuales
        _dump(d[f"usuarios_mensuales_{lado}"], os.path.join(OUT, path, "usuarios.parquet"))

    # histórico: solo los meses calendario (prev/cur se reconstruyen desde current/previous)
    cur_prev_labels = {f"Prev ({d['prev_label']})", f"Actual ({d['cur_label']})"}
    for p in periodos:
        if p["label"] in cur_prev_labels:
            continue
        _dump(p["df"], os.path.join(OUT, "historico", f"snapshot_{p['orden']:02d}.parquet"), COLS_SLIM)

    # serie diaria larga histórica (raw, sin prev/cur; el pipeline los re-anexa)
    hist_serie = pl._load_latest(pl.HIST_DIR, "Horas_de_aprendizaje_*.csv")
    _dump(hist_serie, os.path.join(OUT, "historico", "serie_larga_horas.parquet"))

    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _, fs in os.walk(OUT) for f in fs)
    print(f"\n✅ Listo. dashboard/data/ = {total/1e6:.2f} MB total.")
    print("   Ahora: git add dashboard/data && git commit && git push")


if __name__ == "__main__":
    main()
