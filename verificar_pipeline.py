"""Digest estable de TODA la salida de pipeline.computar.

Sirve para cambiar el pipeline sin miedo: se genera un digest antes, se hace el
cambio, se genera otro y se comparan. Si el hash no cambia, ningun numero del
dashboard cambio. Asi se valido la migracion a dtypes category (arreglo del OOM
en Streamlit Cloud, 23-Sep-2026).

Uso:
    python verificar_pipeline.py antes.txt     # antes de tocar nada
    ...cambios en pipeline.py...
    python verificar_pipeline.py despues.txt
    diff -q antes.txt despues.txt

Si difieren, `sort` de ambos archivos y otro diff dice si cambiaron los VALORES
o solamente el ORDEN de las filas.
"""
import sys, io, os, warnings, hashlib
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
import pipeline as pl

def render(o, nombre, out):
    if isinstance(o, pd.DataFrame):
        d = o.copy()
        # normaliza: categorias -> texto, orden estable de columnas
        for c in d.columns:
            if str(d[c].dtype) == "category":
                d[c] = d[c].astype(object)
        d = d.reindex(sorted(d.columns.astype(str), key=str), axis=1)
        out.write(f"## {nombre} DataFrame shape={d.shape}\n")
        out.write(d.round(6).to_csv(index=False))
    elif isinstance(o, pd.Series):
        s = o.copy()
        if str(s.dtype) == "category":
            s = s.astype(object)
        out.write(f"## {nombre} Series len={len(s)}\n")
        out.write(s.round(6).to_csv() if s.dtype.kind == "f" else s.to_csv())
    elif isinstance(o, dict):
        for k in sorted(o, key=str):
            render(o[k], f"{nombre}.{k}", out)
    elif isinstance(o, (list, tuple)):
        for i, v in enumerate(o):
            render(v, f"{nombre}[{i}]", out)
    elif isinstance(o, float) or isinstance(o, np.floating):
        out.write(f"## {nombre} = {float(o):.6f}\n")
    else:
        out.write(f"## {nombre} = {o!r}\n")

def main(destino):
    base = pl.cargar_base()
    out = io.StringIO()
    out.write(f"marcas = {base['marcas']}\n")
    for marcas in [None] + [[m] for m in base["marcas"]]:
        R = pl.computar(base, marcas)
        R = {k: v for k, v in R.items() if k != "meta"}   # meta trae timestamp
        render(R, f"computar({marcas})", out)
    txt = out.getvalue()
    open(destino, "w").write(txt)
    print(f"{destino}: {len(txt):,} chars  sha1={hashlib.sha1(txt.encode()).hexdigest()}")

if __name__ == "__main__":
    main(sys.argv[1])
