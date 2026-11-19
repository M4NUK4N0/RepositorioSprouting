import numpy as np
import pandas as pd
import streamlit as st

# ============================================================
#  Configuración de la página
#  Tip: para que los colores se vean como se diseñaron, crea
#  .streamlit/config.toml con:   [theme]  base = "light"
# ============================================================
st.set_page_config(
    page_title="Mi Huerta Inteligente",
    page_icon="🌱",
    layout="wide",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@500;600&family=Nunito:wght@400;600;700&display=swap');
.stApp { background: linear-gradient(180deg, #DFF1FB 0, #F6FBF1 380px, #FBF8EE 100%); }
.stApp h1, .stApp h2, .stApp h3, .stApp h4 { font-family: 'Fredoka', sans-serif; color: #2F6B1E; }
.stApp p, .stApp label, .stApp li, .stTabs button { font-family: 'Nunito', sans-serif; color: #2B3A2B; }
.block-container { padding-top: 1.5rem; }

.hero { position: relative; overflow: hidden; border-radius: 28px; height: 210px;
        background: linear-gradient(180deg, #A9DAF3 0, #E6F5FD 100%); margin-bottom: 1.2rem; }
.hero svg { position: absolute; left: 0; width: 100%; }
.hero .nubes { top: 0; height: 100%; }
.hero .pasto { bottom: 0; height: 54px; }
.hero .texto { position: relative; z-index: 2; padding: 26px 34px; }
.hero h1 { margin: 0; font-size: 2.3rem; color: #2F6B1E; }
.hero p { margin: 6px 0 0; font-size: 1.05rem; color: #3C5A3C; }
.drift { animation: drift linear infinite; }
@keyframes drift { from { transform: translateX(-300px); } to { transform: translateX(1500px); } }
@media (prefers-reduced-motion: reduce) { .drift { animation: none; } }

.tarjeta { background: #fff; border: 2px solid #DCE8D2; border-radius: 22px; padding: 16px 12px;
           text-align: center; height: 100%; }
.tarjeta .tit { font-family: 'Fredoka', sans-serif; font-size: 1.1rem; color: #2F6B1E; margin-bottom: 4px; }
.tarjeta .grande { font-family: 'Fredoka', sans-serif; font-size: 2rem; color: #2B3A2B; line-height: 1.1; }
.tarjeta .pie { font-size: .95rem; color: #5B6B5B; margin-top: 4px; }
.tarjeta .icono { font-size: 4.4rem; line-height: 140px; }

.nota { display: flex; gap: 12px; align-items: flex-start; padding: 10px 14px; margin: 8px 0;
        background: #fff; border-radius: 14px; border-left: 6px solid #2E86C1; font-family: 'Nunito', sans-serif; }
.nota.ok { border-color: #4C9A2A; }
.nota.warn { border-color: #F2B632; }
.nota.alerta { border-color: #D9534F; background: #FFF4F2; }
.nota .ic { font-size: 1.4rem; }

.suelo-footer { text-align: center; margin-top: 2.5rem; padding: 14px; border-top: 3px dashed #BFD9B0;
                font-family: 'Nunito', sans-serif; color: #5B6B5B; }
.suelo-footer .plantas { font-size: 1.8rem; letter-spacing: 8px; }
</style>
""", unsafe_allow_html=True)

# ============================================================
#  Constantes del proyecto (iguales a las del código del ESP32)
# ============================================================
ALIAS_TIEMPO = ["_time", "time", "timestamp", "ts", "fecha", "date", "datetime"]
HUM_MOJADO_ADC = 3083
NIVEL_LLENO_ADC = 4095

NOMBRES = {
    "humedad_suelo": "Humedad del suelo (%)",
    "nivel_agua": "Nivel del tanque (%)",
    "valvula": "Válvula (1 = abierta)",
    "humedad_raw": "Humedad (lectura ADC)",
    "nivel_raw": "Nivel (lectura ADC)",
    "alerta_nivel": "Alerta de nivel",
    "alerta_humedad": "Alerta de humedad",
    "led_rojo": "LED rojo",
    "led_amarillo": "LED amarillo",
    "led_verde": "LED verde",
}
COLORES = {
    "humedad_suelo": "#4C9A2A",
    "nivel_agua": "#2E86C1",
    "valvula": "#E0A030",
    "humedad_raw": "#8BC34A",
    "nivel_raw": "#5DADE2",
}


def nombre(c):
    return NOMBRES.get(c, c)


# ============================================================
#  Lectura y preparación de datos
# ============================================================
def convertir_tiempo(serie):
    """Convierte a fecha/hora. Si viene en UTC (InfluxDB), pasa a hora de Colombia."""
    if pd.api.types.is_numeric_dtype(serie):
        unidad = "ms" if serie.max() > 1e11 else "s"
        t = pd.to_datetime(serie, unit=unidad, utc=True, errors="coerce")
        return t.dt.tz_convert("America/Bogota").dt.tz_localize(None)
    tiene_zona = serie.astype(str).str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$").mean() > 0.5
    if tiene_zona:
        t = pd.to_datetime(serie, utc=True, errors="coerce")
        return t.dt.tz_convert("America/Bogota").dt.tz_localize(None)
    return pd.to_datetime(serie, errors="coerce")


def leer_csv(archivo):
    """Lee un CSV simple o una exportación de InfluxDB (formato largo)."""
    df = pd.read_csv(archivo, comment="#")
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]
    if {"_field", "_value"} <= set(df.columns):
        tcol = next((c for c in df.columns if c in ALIAS_TIEMPO), None)
        if tcol is None:
            raise ValueError("El archivo de InfluxDB no trae columna _time.")
        df = df[df["_field"] != "_field"]  # encabezados repetidos entre tablas
        df = df.groupby([tcol, "_field"])["_value"].last().unstack("_field").reset_index()
        df.columns.name = None
    return df


def preparar_datos(df):
    df = df.copy()

    col_tiempo = next((c for c in df.columns if str(c).strip().lower() in ALIAS_TIEMPO), None)
    if col_tiempo is not None:
        df[col_tiempo] = convertir_tiempo(df[col_tiempo])
        df = df.dropna(subset=[col_tiempo]).set_index(col_tiempo).sort_index()
        df.index.name = "Hora"

    # Texto que en realidad es número ("23,5", "true", "false")
    for c in df.columns:
        if pd.api.types.is_bool_dtype(df[c]):
            df[c] = df[c].astype(int)
        elif not pd.api.types.is_numeric_dtype(df[c]):
            txt = df[c].astype(str).str.strip().str.lower()
            txt = txt.replace({"true": "1", "false": "0"})
            conv = pd.to_numeric(txt.str.replace(",", ".", regex=False), errors="coerce")
            if conv.notna().mean() >= 0.9:
                df[c] = conv

    # Si solo vienen las lecturas crudas del ADC, se calculan los porcentajes
    if "humedad_suelo" not in df and "humedad_raw" in df:
        df["humedad_suelo"] = (df["humedad_raw"] / HUM_MOJADO_ADC * 100).clip(0, 100)
    if "nivel_agua" not in df and "nivel_raw" in df:
        df["nivel_agua"] = (df["nivel_raw"] / NIVEL_LLENO_ADC * 100).clip(0, 100)

    numericas = df.select_dtypes(include="number").columns.tolist()
    return df, numericas, col_tiempo


def normalizar(df):
    rango = (df.max() - df.min()).replace(0, 1)
    return (df - df.min()) / rango


def duraciones(df):
    """Segundos que representa cada registro (para medir 'tiempo en cada estado')."""
    unos = np.ones(len(df))
    if not isinstance(df.index, pd.DatetimeIndex) or len(df) < 2:
        return unos
    dt = df.index.to_series().diff().shift(-1).dt.total_seconds()
    med = dt.median()
    if not med > 0:
        return unos
    return dt.fillna(med).clip(upper=med * 5).to_numpy()


def ultimo(df, col):
    s = df[col].dropna() if col in df else pd.Series(dtype=float)
    return float(s.iloc[-1]) if len(s) else None


# ============================================================
#  Interpretación automática de los datos
# ============================================================
def analizar(df, seca, humeda, bajo):
    notas = []  # (nivel, icono, texto)
    dur = duraciones(df)
    hay_hum = "humedad_suelo" in df
    hay_niv = "nivel_agua" in df
    hay_val = "valvula" in df
    hum, niv = ultimo(df, "humedad_suelo"), ultimo(df, "nivel_agua")

    # --- Estado actual ---
    if hum is not None:
        if hum < seca:
            notas.append(("alerta", "🥀", f"El suelo está seco ({hum:.0f} %), por debajo del {seca:.0f} % que activa el riego."))
        elif hum >= humeda:
            notas.append(("ok", "🌿", f"El suelo está bien hidratado ({hum:.0f} %)."))
        else:
            notas.append(("warn", "🌱", f"El suelo está en zona intermedia ({hum:.0f} %): ni seco ni completamente húmedo."))
    if niv is not None:
        if niv < bajo:
            notas.append(("alerta", "🪣", f"El tanque está bajo ({niv:.0f} %). Conviene rellenarlo."))
        else:
            notas.append(("ok", "💧", f"El tanque tiene agua suficiente ({niv:.0f} %)."))
    if hum is not None and niv is not None and hum < seca and niv < bajo:
        notas.insert(0, ("alerta", "🚨", "Suelo seco y tanque bajo al mismo tiempo: la planta no podrá regarse hasta rellenar el tanque."))

    # --- Tiempo en cada estado del suelo ---
    if hay_hum:
        estado = pd.cut(df["humedad_suelo"], [-np.inf, seca, humeda, np.inf], labels=["Seco", "Intermedio", "Húmedo"], right=False)
        t = pd.Series(dur).groupby(estado.to_numpy()).sum()
        pct_seco = t.get("Seco", 0) / dur.sum() * 100
        if pct_seco > 30:
            notas.append(("warn", "☀️", f"El suelo pasó el {pct_seco:.0f} % del tiempo en estado seco."))
        else:
            notas.append(("ok", "🌤️", f"Solo el {pct_seco:.0f} % del tiempo el suelo estuvo seco."))
    else:
        pct_seco = 0

    # --- Válvula ---
    if hay_val:
        v = df["valvula"] > 0.5
        ini = v & ~v.shift(1, fill_value=False)
        aperturas = int(ini.sum())
        pct_abierta = dur[v.to_numpy()].sum() / dur.sum() * 100
        notas.append(("info", "🚿", f"La válvula se abrió {aperturas} vez/veces y estuvo abierta el {pct_abierta:.1f} % del tiempo."))
        if aperturas == 0 and pct_seco > 0:
            notas.append(("warn", "🔧", "El suelo estuvo seco pero la válvula nunca se abrió. Revisa el servo y el cableado."))

        # Efecto del riego: ¿sube la humedad en los 5 minutos siguientes?
        if hay_hum and isinstance(df.index, pd.DatetimeIndex) and aperturas > 0:
            deltas = []
            for t0 in df.index[ini.to_numpy()]:
                ventana = df["humedad_suelo"].loc[t0: t0 + pd.Timedelta(minutes=5)].dropna()
                if len(ventana) >= 2:
                    deltas.append(ventana.max() - ventana.iloc[0])
            if deltas:
                d = float(np.mean(deltas))
                if d >= 1:
                    notas.append(("ok", "💦", f"Cada riego sube la humedad en promedio {d:.1f} puntos en los 5 minutos siguientes."))
                else:
                    notas.append(("warn", "🤔", "El riego casi no sube la humedad (menos de 1 punto en 5 min). Revisa la manguera, el flujo o la posición del sensor."))

    # --- Tendencia del tanque ---
    if hay_niv and isinstance(df.index, pd.DatetimeIndex):
        s = df["nivel_agua"].dropna()
        if len(s) >= 5 and s.index[-1] > s.index[0]:
            x = (s.index - s.index[0]).total_seconds() / 3600
            pendiente = np.polyfit(x, s.to_numpy(), 1)[0]
            if pendiente < -0.05 and niv:
                horas = niv / -pendiente
                tiempo = f"{horas:.1f} horas" if horas < 48 else f"{horas / 24:.1f} días"
                notas.append(("info", "📉", f"El tanque baja unos {-pendiente:.2f} puntos por hora. A ese ritmo se vaciaría en unas {tiempo} (si no lo rellenas)."))
            elif pendiente > 0.05:
                notas.append(("info", "📈", "El nivel del tanque tiende a subir en este periodo."))
            else:
                notas.append(("info", "➖", "El nivel del tanque se mantiene estable en este periodo."))

    # --- Periodo cubierto ---
    if isinstance(df.index, pd.DatetimeIndex) and len(df) > 1:
        dias = df.index[-1] - df.index[0]
        notas.append(("info", "🗓️", f"Se analizaron {len(df)} registros entre {df.index[0]:%d/%m/%Y %H:%M} y {df.index[-1]:%d/%m/%Y %H:%M} ({dias})."))
    return notas


# ============================================================
#  Decoración: nubes, pasto, planta y tanque (SVG)
# ============================================================
def nube(y, escala, dur, delay):
    return (
        f'<g transform="translate(0,{y}) scale({escala})">'
        f'<g class="drift" style="animation-duration:{dur}s;animation-delay:{delay}s">'
        '<g fill="#fff" opacity=".92"><ellipse cx="60" cy="32" rx="62" ry="20"/>'
        '<circle cx="38" cy="20" r="20"/><circle cx="75" cy="14" r="27"/><circle cx="104" cy="26" r="17"/></g>'
        '</g></g>'
    )


def brote(x, h, flor=False):
    s = (
        f'<g transform="translate({x},54)">'
        f'<path d="M0 0 Q3 {-h / 2:.0f} 0 {-h}" stroke="#3E8E2F" stroke-width="3" fill="none" stroke-linecap="round"/>'
        f'<ellipse cx="-8" cy="{-h * 0.62:.0f}" rx="9" ry="4.5" transform="rotate(-30 -8 {-h * 0.62:.0f})" fill="#6BBF59"/>'
        f'<ellipse cx="8" cy="{-h * 0.82:.0f}" rx="9" ry="4.5" transform="rotate(30 8 {-h * 0.82:.0f})" fill="#7FD068"/>'
    )
    if flor:
        s += f'<circle cx="0" cy="{-h - 4}" r="6" fill="#F08CB0"/><circle cx="0" cy="{-h - 4}" r="2.5" fill="#F7D154"/>'
    return s + '</g>'


def hero():
    nubes = "".join(nube(*p) for p in [(18, 1.0, 75, 0), (72, 0.7, 100, -45), (6, 0.55, 125, -90), (100, 0.85, 90, -20)])
    sol = '<circle cx="1110" cy="52" r="30" fill="#F7D154"/><circle cx="1110" cy="52" r="42" fill="#F7D154" opacity=".25"/>'
    pasto = "".join(brote(20 + i * 38, 18 + (i * 7) % 22, flor=(i % 5 == 2)) for i in range(32))
    return (
        '<div class="hero">'
        f'<svg class="nubes" viewBox="0 0 1200 210" preserveAspectRatio="xMidYMid slice" aria-hidden="true">{sol}{nubes}</svg>'
        f'<svg class="pasto" viewBox="0 0 1200 54" preserveAspectRatio="none" aria-hidden="true">'
        f'<rect y="44" width="1200" height="10" fill="#8A5A3B"/>{pasto}</svg>'
        '<div class="texto"><h1>Mi Huerta Inteligente</h1>'
        '<p>Humedad del suelo y nivel del tanque de riego, explicados con tus propios datos.</p></div>'
        '</div>'
    )


POT = (
    '<path d="M40 104 L80 104 L74 134 L46 134 Z" fill="#B5703F"/>'
    '<rect x="36" y="98" width="48" height="9" rx="4" fill="#8A5A3B"/>'
)
PLANTAS = {
    "Seco": (
        '<path d="M60 98 Q60 70 84 62" stroke="#A89A3C" stroke-width="4" fill="none" stroke-linecap="round"/>'
        '<ellipse cx="90" cy="72" rx="14" ry="6" transform="rotate(60 90 72)" fill="#C9A227"/>'
        '<path d="M60 90 Q46 84 38 92" stroke="#A89A3C" stroke-width="3" fill="none" stroke-linecap="round"/>'
        '<ellipse cx="33" cy="100" rx="13" ry="5.5" transform="rotate(62 33 100)" fill="#B98F2B"/>'
    ),
    "Intermedio": (
        '<path d="M60 98 Q58 70 62 46" stroke="#5E9E3A" stroke-width="4" fill="none" stroke-linecap="round"/>'
        '<ellipse cx="44" cy="72" rx="14" ry="6" transform="rotate(-25 44 72)" fill="#8DBF5A"/>'
        '<ellipse cx="78" cy="62" rx="14" ry="6" transform="rotate(25 78 62)" fill="#8DBF5A"/>'
        '<ellipse cx="62" cy="40" rx="6" ry="12" fill="#7FB069"/>'
    ),
    "Húmedo": (
        '<path d="M60 98 L60 44" stroke="#3E8E2F" stroke-width="4" stroke-linecap="round"/>'
        '<ellipse cx="42" cy="80" rx="15" ry="7" transform="rotate(-35 42 80)" fill="#5DBB3F"/>'
        '<ellipse cx="78" cy="74" rx="15" ry="7" transform="rotate(35 78 74)" fill="#6FCF4F"/>'
        '<ellipse cx="44" cy="60" rx="14" ry="6.5" transform="rotate(-30 44 60)" fill="#6FCF4F"/>'
        '<ellipse cx="77" cy="55" rx="14" ry="6.5" transform="rotate(30 77 55)" fill="#5DBB3F"/>'
        '<g fill="#F08CB0"><circle cx="60" cy="22" r="7"/><circle cx="70" cy="29" r="7"/><circle cx="66" cy="40" r="7"/>'
        '<circle cx="54" cy="40" r="7"/><circle cx="50" cy="29" r="7"/></g><circle cx="60" cy="32" r="6" fill="#F7D154"/>'
    ),
}


def planta_svg(estado):
    return f'<svg viewBox="0 0 120 140" width="120" height="140" role="img" aria-label="Planta: suelo {estado.lower()}">{POT}{PLANTAS[estado]}</svg>'


def tanque_svg(p, bajo):
    p = max(0.0, min(100.0, p))
    alto = 110 * p / 100
    y = 15 + 110 - alto
    color = "#E8913A" if p < bajo else "#3FA7E0"
    marcas = "".join(
        f'<line x1="18" x2="30" y1="{15 + 110 * (1 - t / 100):.1f}" y2="{15 + 110 * (1 - t / 100):.1f}" stroke="#6B8E9F" stroke-width="2"/>'
        for t in (25, 50, 75)
    )
    return (
        f'<svg viewBox="0 0 100 140" width="100" height="140" role="img" aria-label="Tanque al {p:.0f} por ciento">'
        '<defs><clipPath id="clipTanque"><rect x="18" y="15" width="64" height="110" rx="12"/></clipPath></defs>'
        '<g clip-path="url(#clipTanque)"><rect x="18" y="15" width="64" height="110" fill="#EAF5FC"/>'
        f'<rect x="18" y="{y:.1f}" width="64" height="{alto:.1f}" fill="{color}"/></g>'
        f'{marcas}<rect x="18" y="15" width="64" height="110" rx="12" fill="none" stroke="#6B8E9F" stroke-width="3"/></svg>'
    )


def tarjeta(titulo, visual, grande, pie):
    return (
        f'<div class="tarjeta"><div class="tit">{titulo}</div>{visual}'
        f'<div class="grande">{grande}</div><div class="pie">{pie}</div></div>'
    )


# ============================================================
#  Encabezado y ajustes
# ============================================================
st.markdown(hero(), unsafe_allow_html=True)

with st.sidebar:
    st.header("☁️ Ajustes")
    st.caption("Los valores por defecto son los del ESP32.")
    seca = st.slider("Suelo seco por debajo de (%)", 5, 50, 20)
    humeda = st.slider("Suelo húmedo desde (%)", 30, 90, 55)
    bajo = st.slider("Tanque bajo por debajo de (%)", 5, 50, 20)

uploaded_file = st.file_uploader(
    "Sube el CSV de tu sistema de riego (exportado de InfluxDB, ThingsBoard o similar)", type=["csv"]
)

if uploaded_file is not None:
    try:
        df1, variables, col_tiempo = preparar_datos(leer_csv(uploaded_file))

        if not variables:
            st.error("No se encontraron columnas numéricas en el archivo.")
            st.stop()

        faltan = [c for c in ("humedad_suelo", "nivel_agua") if c not in df1]
        if faltan:
            st.info("No encontré las columnas " + ", ".join(f"`{c}`" for c in faltan) + ". Mostraré lo que sí hay en el archivo.")
        if col_tiempo is None:
            st.info("No hay columna de tiempo; se usará el número de registro como eje X.")

        tab1, tab2, tab3, tab4, tab5 = st.tabs(
            ["🌱 Resumen", "📈 Gráficos", "📊 Estadísticas", "🔍 Datos y filtros", "🛰️ Sistema"]
        )

        # ----------------------------------------------------
        #  TAB 1 · Resumen
        # ----------------------------------------------------
        with tab1:
            hum, niv = ultimo(df1, "humedad_suelo"), ultimo(df1, "nivel_agua")
            val = ultimo(df1, "valvula")
            c1, c2, c3 = st.columns(3)

            with c1:
                if hum is not None:
                    est = "Seco" if hum < seca else ("Húmedo" if hum >= humeda else "Intermedio")
                    st.markdown(tarjeta("Suelo", planta_svg(est), f"{hum:.0f} %", f"Estado: {est.lower()}"), unsafe_allow_html=True)
                else:
                    st.markdown(tarjeta("Suelo", '<div class="icono">🪴</div>', "—", "Sin datos de humedad"), unsafe_allow_html=True)
            with c2:
                if niv is not None:
                    pie = "Tanque bajo: hay que rellenar" if niv < bajo else "Agua suficiente"
                    st.markdown(tarjeta("Tanque", tanque_svg(niv, bajo), f"{niv:.0f} %", pie), unsafe_allow_html=True)
                else:
                    st.markdown(tarjeta("Tanque", '<div class="icono">🪣</div>', "—", "Sin datos de nivel"), unsafe_allow_html=True)
            with c3:
                if val is not None:
                    abierta = val > 0.5
                    st.markdown(
                        tarjeta("Válvula", f'<div class="icono">{"🚿" if abierta else "💤"}</div>',
                                "Regando" if abierta else "Cerrada", "Último estado registrado"),
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(tarjeta("Válvula", '<div class="icono">🚿</div>', "—", "Sin datos de válvula"), unsafe_allow_html=True)

            st.subheader("☁️ Lo que cuentan tus datos")
            for nivel, icono, texto in analizar(df1, seca, humeda, bajo):
                st.markdown(f'<div class="nota {nivel}"><span class="ic">{icono}</span><div>{texto}</div></div>', unsafe_allow_html=True)

        # ----------------------------------------------------
        #  TAB 2 · Gráficos
        # ----------------------------------------------------
        with tab2:
            st.subheader("Gráficos")
            base = [c for c in ("humedad_suelo", "nivel_agua") if c in variables]
            col_a, col_b = st.columns([3, 1])
            with col_a:
                vars_graf = st.multiselect(
                    "Variables a graficar", variables,
                    default=base or variables[:2], format_func=nombre,
                )
            with col_b:
                chart_type = st.selectbox("Tipo de gráfico", ["Línea", "Área", "Barra"])

            k1, k2 = st.columns(2)
            normalizado = k1.checkbox("Normalizar escalas (0–1)", help="Para comparar variables con unidades distintas.")
            umbrales = k2.checkbox("Mostrar umbrales de humedad", value=True)

            if not vars_graf:
                st.warning("Seleccione al menos una variable.")
            else:
                datos = df1[vars_graf]
                colores = [COLORES.get(c, "#8A5A3B") for c in vars_graf]
                if normalizado:
                    datos = normalizar(datos)
                elif umbrales and chart_type == "Línea" and "humedad_suelo" in vars_graf:
                    datos = datos.assign(**{"Umbral seco": seca, "Umbral húmedo": humeda})
                    colores += ["#D9534F", "#7FB069"]
                datos = datos.rename(columns=NOMBRES)
                if chart_type == "Línea":
                    st.line_chart(datos, color=colores)
                elif chart_type == "Área":
                    st.area_chart(datos, color=colores)
                else:
                    st.bar_chart(datos, color=colores)

            if "valvula" in df1:
                st.write("#### 🚿 Cuándo estuvo abierta la válvula")
                st.area_chart(df1[["valvula"]].rename(columns=NOMBRES), color=["#E0A030"])

        # ----------------------------------------------------
        #  TAB 3 · Estadísticas
        # ----------------------------------------------------
        with tab3:
            st.subheader("Análisis estadístico")
            st.write("#### Resumen de todas las variables")
            st.dataframe(df1[variables].describe().T.rename(index=NOMBRES).round(2))

            if "humedad_suelo" in df1:
                st.write("#### Tiempo del suelo en cada estado")
                estado = pd.cut(df1["humedad_suelo"], [-np.inf, seca, humeda, np.inf],
                                labels=["Seco", "Intermedio", "Húmedo"], right=False)
                t = pd.Series(duraciones(df1)).groupby(estado.to_numpy()).sum()
                pct = (t / t.sum() * 100).reindex(["Seco", "Intermedio", "Húmedo"]).fillna(0).round(1)
                st.bar_chart(pct.rename("% del tiempo"), color="#4C9A2A")

            st.write("#### Detalle por variable")
            var_stats = st.selectbox("Variable", variables, key="var_stats", format_func=nombre)
            serie = df1[var_stats].dropna()
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Promedio", f"{serie.mean():.2f}")
            m2.metric("Máximo", f"{serie.max():.2f}")
            m3.metric("Mínimo", f"{serie.min():.2f}")
            m4.metric("Desv. estándar", f"{serie.std():.2f}")

            if len(variables) >= 2:
                st.write("#### Correlación entre variables")
                st.dataframe(df1[variables].corr().rename(index=NOMBRES, columns=NOMBRES).round(2))
                st.caption("Cerca de 1 o −1: relación lineal fuerte. Cerca de 0: poca relación. "
                           "Es normal que la válvula y la humedad no estén muy correlacionadas: el riego es breve y el suelo tarda en responder.")

        # ----------------------------------------------------
        #  TAB 4 · Datos y filtros
        # ----------------------------------------------------
        with tab4:
            st.subheader("Filtros de datos")
            var_filtro = st.selectbox("Variable a filtrar", variables, key="var_filtro", format_func=nombre)
            min_value, max_value = float(df1[var_filtro].min()), float(df1[var_filtro].max())

            if min_value == max_value:
                st.warning(f"⚠️ Todos los valores de {nombre(var_filtro)} son iguales: {min_value:.2f}")
                st.dataframe(df1)
            else:
                rango = st.slider(f"Rango de {nombre(var_filtro)}", min_value, max_value,
                                  (min_value, max_value), key=f"rango_{var_filtro}")
                filtrado = df1[df1[var_filtro].between(rango[0], rango[1])]
                st.write(f"**{len(filtrado)}** de {len(df1)} registros entre {rango[0]:.2f} y {rango[1]:.2f}:")
                st.dataframe(filtrado)
                st.download_button(
                    "⬇️ Descargar datos filtrados (CSV)",
                    data=filtrado.to_csv().encode("utf-8"),
                    file_name=f"datos_filtrados_{var_filtro}.csv",
                    mime="text/csv",
                )

        # ----------------------------------------------------
        #  TAB 5 · Sistema
        # ----------------------------------------------------
        with tab5:
            st.subheader("Información del sistema")
            col1, col2 = st.columns(2)

            with col1:
                st.write("### 📍 Ubicación")
                st.map(pd.DataFrame({"lat": [6.2006], "lon": [-75.5783]}), zoom=15)
                st.write("**Universidad EAFIT**, Medellín · ~1,495 m s. n. m.")

                st.write("### 🔌 Conexiones del ESP32")
                st.table(pd.DataFrame({
                    "Componente": ["Sensor de nivel", "Sensor de humedad", "Servo (válvula)",
                                   "LED verde", "LED amarillo", "LED rojo"],
                    "Pin": ["GPIO 33", "GPIO 32", "GPIO 13", "GPIO 5", "GPIO 19", "GPIO 18"],
                    "Indica": ["Agua en el tanque", "Humedad del suelo", "Abre/cierra el riego",
                               "Suelo húmedo", "Tanque bajo (parpadea)", "Suelo seco"],
                }))

            with col2:
                st.write("### 🤖 Cómo decide el riego")
                st.markdown(
                    "- **Automático:** la válvula se abre cuando la humedad baja de 20 % y se cierra al llegar a 55 %.\n"
                    "- **Manual (ThingsBoard):** el botón abre la válvula 5 segundos.\n"
                    "- **Bloqueo:** después de una acción manual, el automático espera 10 segundos.\n"
                    "- **Alerta de tanque:** el LED amarillo parpadea cuando el nivel es bajo."
                )
                st.write("### 📄 Este archivo")
                st.write(f"- Variables: {', '.join(nombre(v) for v in variables)}")
                st.write(f"- Registros: {len(df1)}")
                if col_tiempo is not None and len(df1) > 0:
                    st.write(f"- Desde: {df1.index.min():%Y-%m-%d %H:%M}")
                    st.write(f"- Hasta: {df1.index.max():%Y-%m-%d %H:%M}")
                    st.caption("Horas en zona horaria de Colombia (UTC−5) cuando el archivo venía en UTC.")

    except Exception as e:
        st.error(f"Error al procesar el archivo: {str(e)}")
        st.info("Asegúrese de que el CSV tenga columnas como humedad_suelo y nivel_agua, y una columna de tiempo.")
else:
    st.markdown('<div class="nota"><span class="ic">🌥️</span><div>Sube un archivo CSV para ver cómo están tu planta y tu tanque.</div></div>',
                unsafe_allow_html=True)

st.markdown(
    '<div class="suelo-footer"><div class="plantas">🌱 🌿 🌻 🪴 🌷 🌿 🌱</div>'
    'Sistema de riego automático · Universidad EAFIT, Medellín, Colombia</div>',
    unsafe_allow_html=True,
)
