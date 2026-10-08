from datetime import datetime, timedelta
import re
import gspread
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

# Configuración de la página
st.set_page_config(
    page_title="horas Stock",
    page_icon="https://cdn-icons-png.flaticon.com/512/194/194978.png",
    layout="wide",
)

# ------------------ ESTILOS CSS ------------------
st.markdown(
    """
    <style>
        html, body, [class*="css"] { font-size: 18px !important; }
        [data-testid="stMetricValue"] { font-size: 1.8rem !important; }
        [data-testid="stMetricLabel"] { font-size: 1.1rem !important; }
        .stCaption { font-size: 1rem !important; }
        .stDataFrame, .stTable, [data-testid="stDataEditor"] { font-size: 1rem !important; }
        
        div[data-testid="stProgress"] > div > div > div {
            background-image: linear-gradient(90deg, #3b82f6, #1d4ed8, #60a5fa);
            background-size: 200% 100%;
            animation: gradientAnimation 1.5s ease infinite;
            transition: width 0.6s ease-in-out;
        }

        @keyframes gradientAnimation {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }
    </style>
""",
    unsafe_allow_html=True,
)

# ------------------ LISTADO DE FESTIVOS EN GRANADA Y ESPAÑA ------------------
FESTIVOS_GRANADA = {
    # 2024
    "01-01-2024", "02-01-2024", "06-01-2024", "28-02-2024", "28-03-2024", "29-03-2024",
    "01-05-2024", "30-05-2024", "15-08-2024", "12-10-2024", "01-11-2024", "06-12-2024",
    "09-12-2024", "25-12-2024",
    # 2025
    "01-01-2025", "02-01-2025", "06-01-2025", "28-02-2025", "17-04-2025", "18-04-2025",
    "01-05-2025", "19-06-2025", "15-08-2025", "12-10-2025", "13-10-2025", "01-11-2025",
    "06-12-2025", "08-12-2025", "25-12-2025",
    # 2026
    "01-01-2026", "02-01-2026", "06-01-2026", "28-02-2026", "02-04-2026", "03-04-2026",
    "01-05-2026", "04-06-2026", "15-08-2026", "12-10-2026", "01-11-2026", "02-11-2026",
    "06-12-2026", "07-12-2026", "08-12-2026", "25-12-2026"
}

def es_dia_laborable_por_defecto(dt_obj):
    """Fuerza FALSE para sábados, domingos y festivos de Granada/España."""
    if dt_obj.weekday() >= 5:  # Sábado (5) o Domingo (6)
        return False
    fecha_fmt = dt_obj.strftime("%d-%m-%Y")
    if fecha_fmt in FESTIVOS_GRANADA:
        return False
    return True

# ------------------ CONEXIÓN GOOGLE SHEETS ------------------
@st.cache_resource
def conectar_gspread():
    credenciales_dict = dict(st.secrets["gcp_service_account"])
    gc = gspread.service_account_from_dict(credenciales_dict)
    spreadsheet_id = "1FuKT6RSIbmgQlr7LdSiYBHkuMguhfN4Yd_8OPsdCt6E"
    sh = gc.open_by_key(spreadsheet_id)
    return sh.get_worksheet(0)

worksheet = conectar_gspread()

# ------------------ AUXILIARES ------------------
meses_espanol = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
}
meses_espanol_lower = {k: v.lower() for k, v in meses_espanol.items()}
dias_semana_lower = {0: "L - ", 1: "M - ", 2: "X - ", 3: "J - ", 4: "V - ", 5: "S - ", 6: "D - "}

def limpiar_fecha(fec_str):
    fec_str = str(fec_str).strip().replace("'", "")
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(fec_str, fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue
    return fec_str

def fecha_a_formato_humano(fec_str):
    try:
        dt = datetime.strptime(fec_str, "%d-%m-%Y")
        return f"{dias_semana_lower[dt.weekday()]} {dt.day} de {meses_espanol_lower[dt.month]}"
    except Exception:
        return fec_str

def formato_humano_a_fecha(humano_str):
    humano_str = str(humano_str).strip().lower()
    try:
        datetime.strptime(humano_str, "%d-%m-%Y")
        return humano_str
    except ValueError:
        pass

    hoy_anio = datetime.now().year
    for num_mes, nombre_mes in meses_espanol_lower.items():
        if nombre_mes in humano_str:
            numeros = re.findall(r"\d+", humano_str)
            if numeros:
                try:
                    return datetime(hoy_anio, num_mes, int(numeros[0])).strftime("%d-%m-%Y")
                except ValueError:
                    pass
    return humano_str

def obtener_datos_hoja():
    try:
        filas = worksheet.get_all_values()
    except Exception:
        return {}, {}

    diccionario_registros, diccionario_laboral = {}, {}
    if not filas or len(filas) <= 1:
        return diccionario_registros, diccionario_laboral

    for fila in filas[1:]:
        if not fila or len(fila) < 2:
            continue
        fecha = limpiar_fecha(fila[0])
        if not fecha or fecha.lower() == "fecha":
            continue

        try:
            horas = float(str(fila[1]).strip().replace(",", ".")) if str(fila[1]).strip() != "" else 0.0
        except ValueError:
            horas = 0.0

        try:
            dt_temp = datetime.strptime(fecha, "%d-%m-%Y")
            def_lab = es_dia_laborable_por_defecto(dt_temp)
        except Exception:
            def_lab = True

        raw_laboral = fila[2] if len(fila) > 2 else ""
        # Si la fecha es fin de semana/festivo, aseguramos False salvo que explícitamente se guardara otro valor
        if raw_laboral != "":
            es_lab = str(raw_laboral).strip().lower() in ["true", "1", "yes", "si", "sí"]
        else:
            es_lab = def_lab

        diccionario_registros[fecha] = diccionario_registros.get(fecha, 0.0) + horas
        diccionario_laboral[fecha] = es_lab

    return diccionario_registros, diccionario_laboral

def formatear_horas(total_decimales):
    negativo = total_decimales < 0
    total_decimales = abs(total_decimales)
    h = int(total_decimales)
    m = int(round((total_decimales - h) * 60))
    if m == 60:
        h += 1
        m = 0
    res = f"{h} h y {m} min"
    return f"- {res}" if negativo else res

def parsear_horas_texto(valor):
    if pd.isnull(valor):
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    val_str = str(valor).lower().strip()
    try:
        if "h" in val_str or "min" in val_str:
            partes = val_str.replace(" y ", " ").split()
            h, m = 0.0, 0.0
            for i, p in enumerate(partes):
                if "h" in p and i > 0: h = float(partes[i - 1])
                elif "min" in p and i > 0: m = float(partes[i - 1])
            return h + (m / 60.0)
        return float(val_str.replace(",", "."))
    except Exception:
        return 0.0

def obtener_dias_laborables_mes(anio, mes, laboral_dict):
    primero = datetime(anio, mes, 1)
    siguiente = datetime(anio + 1, 1, 1) if mes == 12 else datetime(anio, mes + 1, 1)
    laborables = 0
    curr = primero
    while curr < siguiente:
        f_str = curr.strftime("%d-%m-%Y")
        def_lab = es_dia_laborable_por_defecto(curr)
        if laboral_dict.get(f_str, def_lab):
            laborables += 1
        curr += timedelta(days=1)
    return max(laborables, 1)

def calcular_totales(diccionario_registros, laboral_dict, horas_cronometro_extra=0.0):
    hoy_calc = datetime.now()
    hoy_sin_hora = hoy_calc.replace(hour=0, minute=0, second=0, microsecond=0)
    hoy_str_calc = hoy_calc.strftime("%d-%m-%Y")

    tot_hoy = diccionario_registros.get(hoy_str_calc, 0.0) + horas_cronometro_extra
    tot_sem, tot_mes = 0.0, 0.0

    inicio_semana = hoy_sin_hora if hoy_calc.weekday() == 0 else hoy_sin_hora - timedelta(days=hoy_calc.weekday())
    inicio_mes = hoy_sin_hora.replace(day=1)

    for f_str, horas in diccionario_registros.items():
        try:
            f_dt = datetime.strptime(f_str, "%d-%m-%Y")
            if inicio_semana <= f_dt <= hoy_calc: tot_sem += horas
            if inicio_mes <= f_dt <= hoy_calc: tot_mes += horas
        except ValueError:
            pass

    tot_sem += horas_cronometro_extra
    tot_mes += horas_cronometro_extra

    ayer_sin_hora = hoy_sin_hora - timedelta(days=1)
    inicio_deuda = datetime(2026, 7, 22)

    deuda_acumulada = 0.0
    horas_totales_obligatorio = 0.0
    curr = inicio_deuda

    while curr <= ayer_sin_hora:
        f_str = curr.strftime("%d-%m-%Y")
        def_lab = es_dia_laborable_por_defecto(curr)
        es_lab = laboral_dict.get(f_str, def_lab)
        h_trabajadas = diccionario_registros.get(f_str, 0.0)

        if es_lab:
            dias_lab_mes = obtener_dias_laborables_mes(curr.year, curr.month, laboral_dict)
            objetivo_diario = 93.0 / dias_lab_mes
            horas_totales_obligatorio += objetivo_diario
            deuda_acumulada += (objetivo_diario - h_trabajadas)
        else:
            # Sábados, domingos y festivos no suman objetivo y restan deuda si se trabaja
            deuda_acumulada -= h_trabajadas

        curr += timedelta(days=1)

    horas_totales_trabajadas = sum(diccionario_registros.values())

    def calcular_deuda_mes(inicio_m, fin_m):
        d_mes = 0.0
        c = inicio_m
        limite = min(fin_m, ayer_sin_hora)
        while c <= limite:
            if c >= datetime(2026, 7, 22):
                f_str = c.strftime("%d-%m-%Y")
                def_lab = es_dia_laborable_por_defecto(c)
                es_lab = laboral_dict.get(f_str, def_lab)
                h_trab = diccionario_registros.get(f_str, 0.0)

                if es_lab:
                    dias_lab = obtener_dias_laborables_mes(c.year, c.month, laboral_dict)
                    d_mes += ((93.0 / dias_lab) - h_trab)
                else:
                    d_mes -= h_trab
            c += timedelta(days=1)
        return d_mes

    d_julio = calcular_deuda_mes(datetime(2026, 7, 22), datetime(2026, 7, 31))
    d_agosto = calcular_deuda_mes(datetime(2026, 8, 1), datetime(2026, 8, 31))
    d_sept = calcular_deuda_mes(datetime(2026, 9, 1), datetime(2026, 9, 30))
    d_oct = calcular_deuda_mes(datetime(2026, 10, 1), datetime(2026, 10, 31))

    return (
        round(tot_hoy, 2), round(tot_sem, 2), round(tot_mes, 2), round(deuda_acumulada, 2),
        inicio_semana, inicio_mes, round(d_julio, 2), round(d_agosto, 2),
        round(d_sept, 2), round(d_oct, 2), round(horas_totales_obligatorio, 2),
        round(horas_totales_trabajadas, 2)
    )

def guardar_todo_en_sheet(diccionario_registros, diccionario_laboral):
    try:
        worksheet.clear()
        datos_guardar = [["Fecha", "Horas", "Laboral"]]
        fechas_ord = sorted(diccionario_registros.keys(), key=lambda x: datetime.strptime(x, "%d-%m-%Y"))

        for fec in fechas_ord:
            dt_temp = datetime.strptime(fec, "%d-%m-%Y")
            def_lab = es_dia_laborable_por_defecto(dt_temp)
            # Garantiza que fines de semana/festivos vacíos o automáticos sean False
            val_l = str(diccionario_laboral.get(fec, def_lab))
            datos_guardar.append([f"'{fec}", float(diccionario_registros[fec]), val_l])

        worksheet.append_rows(datos_guardar, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        st.error(f"Error al sincronizar con Google Sheets: {e}")
        return False

# ------------------ ESTADO Y CARGA ------------------
if "registros" not in st.session_state or "laboral" not in st.session_state:
    reg, lab = obtener_datos_hoja()
    st.session_state["registros"] = reg
    st.session_state["laboral"] = lab

registros_actuales = st.session_state["registros"]
laboral_actuales = st.session_state["laboral"]

(
    tot_hoy, tot_sem, tot_mes, deuda_horas, inicio_sem_dt, inicio_mes_dt,
    deuda_julio, deuda_agosto, deuda_septiembre, deuda_octubre,
    horas_totales_obligatorio, horas_totales_trabajadas
) = calcular_totales(registros_actuales, laboral_actuales, 0.0)

# ------------------ INTERFAZ PRINCIPAL ------------------
st.title("Control horas work")

if st.button("🔄 Recargar datos de Google Sheets"):
    reg, lab = obtener_datos_hoja()
    st.session_state["registros"] = reg
    st.session_state["laboral"] = lab
    st.rerun()

st.markdown("---")

col_izq, col_der = st.columns([1.1, 0.9])

with col_izq:
    st.markdown("### Registro Manual / Cronómetro")
    with st.container(border=True):
        col_r1, col_r2, col_r3, col_r4 = st.columns([1.2, 0.9, 0.9, 1.0])
        with col_r1:
            input_fecha = st.text_input("Fecha:", value=datetime.now().strftime("%d-%m-%Y"))
        with col_r2:
            input_horas = st.number_input("Horas:", min_value=0, value=0, step=1)
        with col_r3:
            input_minutos = st.number_input("Minutos:", min_value=0, max_value=59, value=0, step=1)
        with col_r4:
            st.write("")
            st.write("")
            btn_guardar = st.button("Registrar", use_container_width=True)

        if btn_guardar:
            horas_nuevas = round(input_horas + (input_minutos / 60), 2)
            fec = limpiar_fecha(input_fecha)
            if horas_nuevas > 0:
                st.session_state["registros"][fec] = st.session_state["registros"].get(fec, 0.0) + horas_nuevas
                try:
                    dt_temp = datetime.strptime(fec, "%d-%m-%Y")
                    def_lab = es_dia_laborable_por_defecto(dt_temp)
                except Exception:
                    def_lab = True
                laboral_actuales[fec] = laboral_actuales.get(fec, def_lab)
                guardar_todo_en_sheet(st.session_state["registros"], st.session_state["laboral"])
                st.success("¡Guardado correctamente!")
                st.rerun()

    st.markdown("---")
    st.markdown("### Resumen Actual")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Hoy", formatear_horas(tot_hoy))
    with c2:
        st.metric("Semana", formatear_horas(tot_sem))
    with c3:
        st.metric("Mes", formatear_horas(tot_mes))

with col_der:
    st.markdown("### Horas a recuperar")
    with st.container(border=True):
        st.metric("Deuda pendiente total", formatear_horas(deuda_horas))
        st.caption("Sábados, domingos y festivos en Granada/España son no laborables (False). No suman deuda y cualquier hora trabajada se descuenta.")

        with st.popover("Detalles de deuda"):
            st.write(f"• **Julio (desde 22):** {formatear_horas(deuda_julio)}")
            st.write(f"• **Agosto:** {formatear_horas(deuda_agosto)}")
            st.write(f"• **Septiembre:** {formatear_horas(deuda_septiembre)}")
            st.write(f"• **Octubre:** {formatear_horas(deuda_octubre)}")

    st.markdown("---")
    st.subheader("Historial y Edición de Días")

    lista_datos = []
    for f, h in registros_actuales.items():
        try:
            dt_t = datetime.strptime(f, "%d-%m-%Y")
            def_l = es_dia_laborable_por_defecto(dt_t)
        except Exception:
            def_l = True
        is_l = laboral_actuales.get(f, def_l)
        lista_datos.append({"Fecha": f, "Horas": h, "Laboral": is_l})

    df_global = pd.DataFrame(lista_datos)
    if not df_global.empty:
        df_global["Fecha_dt"] = pd.to_datetime(df_global["Fecha"], format="%d-%m-%Y", errors="coerce")
        df_global_asc = df_global.sort_values(by="Fecha_dt", ascending=True).copy()
        df_global_asc["Mes_Nombre"] = df_global_asc["Fecha_dt"].apply(
            lambda x: f"{meses_espanol[x.month]} {x.year}" if pd.notnull(x) else "Desconocido"
        )
        meses_unicos = df_global_asc.sort_values(by="Fecha_dt", ascending=False)["Mes_Nombre"].unique().tolist()

        if meses_unicos:
            pestañas = st.tabs(meses_unicos)
            for i, mes_nom in enumerate(meses_unicos):
                with pestañas[i]:
                    df_mes = df_global_asc[df_global_asc["Mes_Nombre"] == mes_nom][["Fecha", "Horas", "Laboral"]].reset_index(drop=True)
                    df_mes_vis = df_mes.copy()
                    df_mes_vis["Fecha"] = df_mes_vis["Fecha"].apply(fecha_a_formato_humano)
                    df_mes_vis["Horas"] = df_mes_vis["Horas"].apply(formatear_horas)

                    df_editado = st.data_editor(
                        df_mes_vis,
                        key=f"editor_mes_{i}_{mes_nom}",
                        use_container_width=True,
                        hide_index=True,
                    )

                    if not df_editado.equals(df_mes_vis):
                        fechas_conv = df_editado["Fecha"].apply(formato_humano_a_fecha)
                        df_global_asc.loc[df_global_asc["Mes_Nombre"] == mes_nom, "Fecha"] = fechas_conv.values
                        df_global_asc.loc[df_global_asc["Mes_Nombre"] == mes_nom, "Horas"] = df_editado["Horas"].apply(parsear_horas_texto).values
                        df_global_asc.loc[df_global_asc["Mes_Nombre"] == mes_nom, "Laboral"] = df_editado["Laboral"].values

                        nuevo_reg, nuevo_lab = {}, {}
                        for _, r in df_global_asc.iterrows():
                            f_l = limpiar_fecha(r["Fecha"])
                            if f_l:
                                nuevo_reg[f_l] = parsear_horas_texto(r["Horas"])
                                nuevo_lab[f_l] = bool(r["Laboral"])

                        guardar_todo_en_sheet(nuevo_reg, nuevo_lab)
                        st.session_state["registros"] = nuevo_reg
                        st.session_state["laboral"] = nuevo_lab
                        st.success("Cambios guardados.")
                        st.rerun()

# ------------------ GRÁFICOS WEB ------------------
st.markdown("---")
st.subheader("📊 Gráficos y Estadísticas")

if not df_global.empty:
    col_g1, col_g2 = st.columns(2)

    # 1. Gráfico de Horas trabajadas por mes
    with col_g1:
        st.markdown("#### Horas trabajadas por mes")
        df_meses = df_global_asc.groupby("Mes_Nombre", sort=False)["Horas"].sum().reset_index()
        fig1, ax1 = plt.subplots(figsize=(6, 4))
        ax1.bar(df_meses["Mes_Nombre"], df_meses["Horas"], color="#3b82f6")
        ax1.set_ylabel("Horas")
        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        st.pyplot(fig1)

    # 2. Gráfico de comparación Deuda vs Trabajadas
    with col_g2:
        st.markdown("#### Balance global de horas")
        fig2, ax2 = plt.subplots(figsize=(6, 4))
        categorias = ["Trabajadas", "Obligatorias", "Deuda Pendiente"]
        valores = [horas_totales_trabajadas, horas_totales_obligatorio, max(0, deuda_horas)]
        colores = ["#22c55e", "#64748b", "#ef4444"]
        ax2.bar(categorias, valores, color=colores)
        ax2.set_ylabel("Horas")
        plt.tight_layout()
        st.pyplot(fig2)
