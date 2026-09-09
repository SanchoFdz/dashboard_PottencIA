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
  la app la usa. Es lo que se sube al repo y despliega en Streamlit Cloud (~1.3 MB).
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
4. En el dashboard pulsa **🔄 Recargar datos**.

No hay que tocar código: el motor detecta automáticamente el archivo más reciente de
cada carpeta (`load_latest`, igual que el notebook).

## Secciones

| # | Sección | Fuente | Equivale a lámina |
|---|---------|--------|-------------------|
| ① | Panorama del mes (KPIs + por marca) | serie diaria + snapshot | s1_panorama_* |
| ② | Tendencias diarias | serie diaria | s1_tendencias_diarias |
| ③ | Segmentación de usuarios | snapshot usuario×LE | s1_segmentacion_* |
| ④ | Avance y abandono (tramos) | snapshot usuario×LE | s1_abandono_* |
| ⑤ | Cursos (top/bottom LEs) | snapshot usuario×LE | s1_top5/bottom5_* |
| ⑥ | El pulso (serie larga anotada) | serie diaria larga | s2a_serie_larga |
| ⑦ | Growth accounting (global + marca) | panel histórico | s2b_growth_* |
| ⑧ | Retención por cohorte | panel histórico | s2c_cohortes |
| ⑨ | Gancho vs callejón (lift por LE) | panel histórico | s2d_gancho_vs_callejon |

## Arquitectura

- **`pipeline.py`** — motor de datos puro (sin Streamlit). Replica celda por celda las
  definiciones canónicas del comité: filtro de test, mapa de marcas, tramos, segmentos
  por horas, growth accounting, cohortes y lift de retención. Es la única pieza que hay
  que mantener sincronizada si el notebook cambia una definición.
- **`app.py`** — UI Streamlit con gráficas Plotly interactivas y navegación por secciones.

> ⚠️ **Nota de medición** (heredada del deck): los KPIs de panorama salen de la *serie
> diaria de plataforma* y la segmentación del *snapshot usuario×LE*; reportan universos
> distintos (la serie diaria mide ~3× las horas). Nunca sumar ni cruzar ambos números.
