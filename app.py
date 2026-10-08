from datetime import datetime, timedelta
import time
import gspread
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

# Configuración de la página en ancho ampliado para las dos columnas
st.set_page_config(
    page_title="horas Stock",
    page_icon="https://cdn-icons-png.flaticon.com/512/194/194978.png",
    layout="wide",
)

# ------------------ ESTILOS CSS Y ANIMACIÓN DE DEGRADADOS ------------------
st.markdown(
    """
    <style>
        html, body, [class*="css"] {
            font-size: 18px !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.8rem !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 1.1rem !important;
        }
        .stCaption {
            font-size: 1rem !important;
        }
        .stDataFrame, .stTable, [data-testid="stDataEditor"] {
            font-size: 1rem !important;
        }
        [data-testid="stDataEditor"] div[data-baseweb="input"] input,
        [data-testid="stDataEditor"] [role="gridcell"] {
            white-space: normal !important;
            word-wrap: break-word !important;
            overflow-wrap: break-word !important;
        }
        
        div[data-testid="stVerticalBlock"] > div[data-testid="stHorizontalBlock"] > div > div[data-testid="stVerticalBlock"] > div[data-testid="stContainer"] {
            height: 175px !important;
            display: flex !important;
            flex-direction: column !important;
            justify-content: space-between !important;
        }
        
        div[data-testid="stProgress"] > div > div > div {
            background-image: linear-gradient(90deg, #3b82f6, #1d4ed8, #60a5fa);
            background-size: 200% 100%;
            animation: gradientAnimation 1.5s ease infinite;
            transition: width 0.6s ease-in-out;
        }

        div[data-testid="stProgress"] div[aria-valuenow="100"] > div > div,
        div[data-testid="stProgress"] div[aria-valuenow="100.0"] > div > div {
            background-image: linear-gradient(90deg, #ec4899, #be185d, #f472b6) !important;
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

# ------------------ CONEXIÓN CON GOOGLE SHEETS ------------------
@st.cache_resource
def conectar_gspread():
    credenciales_dict = dict(st.secrets["gcp_service_account"])
    gc = gspread.service_account_from_dict(credenciales_dict)
    spreadsheet_id = "1FuKT6RSIbmgQlr7LdSiYBHkuMguhfN4Yd_8OPsdCt6E"
    sh = gc.open_by_key(spreadsheet_id)
    worksheet = sh.get_worksheet(0)
    return worksheet

worksheet = conectar_gspread()

# ------------------ DICCIONARIOS Y FUNCIONES ------------------
meses_espanol = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
}

meses_espanol_lower = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
}

dias_semana_lower = {
    0: "L - ", 1: "M - ", 2: "X - ", 3: "J - ", 4: "V - ", 5: "S - ", 6: "D - "
}

def limpiar_fecha(fec_str):
    fec_str = str(fec_str).strip().replace("'", "")
    try:
        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(fec_str, fmt)
                return dt.strftime("%d-%m-%Y")
            except ValueError:
                continue
    except Exception:
        pass
    return fec_str

def fecha_a_formato_humano(fec_str):
    try:
        dt = datetime.strptime(fec_str, "%d-%m-%Y")
        dia_sem = dias_semana_lower[dt.weekday()]
        mes = meses_espanol_lower[dt.month]
        return f"{dia_sem} {dt.day} de {mes}"
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
            import re
            numeros = re.findall(r"\d+", humano_str)
            if numeros:
                dia = int(numeros[0])
                try:
                    dt = datetime(hoy_anio, num_mes, dia)
                    return dt.strftime("%d-%m-%Y")
                except ValueError:
                    pass
    return humano_str

def obtener_datos_hoja():
    try:
        filas = worksheet.get_all_values()
    except Exception:
        return {}, {}

    diccionario_registros = {}
    diccionario_laboral = {}
    
    if not filas or len(filas) <= 1:
        return diccionario_registros, diccionario_laboral

    for fila in filas[1:]:
        if not fila or len(fila) < 2:
            continue
        
        fecha_raw = fila[0]
        raw_horas = fila[1]
        raw_laboral = fila[2] if len(fila) > 2 else ""
        
        fecha = limpiar_fecha(fecha_raw)
        if not fecha or fecha.lower() == "fecha":
            continue

        try:
            horas = float(str(raw_horas).strip().replace(",", ".")) if str(raw_horas).strip() != "" else 0.0
        except ValueError:
            horas = 0.0

        # Determinar si es laborable: por defecto L-V laborable (True), S-D no laborable (False)
        try:
            dt_temp = datetime.strptime(fecha, "%d-%m-%Y")
            def_lab = dt_temp.weekday() < 5
        except:
            def_lab = True

        if raw_laboral != "":
            es_lab = str(raw_laboral).strip().lower() in ["true", "1", "yes", "si", "sí"]
        else:
            es_lab = def_lab

        if fecha in diccionario_registros:
            diccionario_registros[fecha] += horas
        else:
            diccionario_registros[fecha] = horas
            
        diccionario_laboral[fecha] = es_lab

    return diccionario_registros, diccionario_laboral

def formatear_horas(total_decimales):
    negativo = total_decimales < 0
    total_decimales = abs(total_decimales)

    horas_enteras = int(total_decimales)
    minutos_restantes = int(round((total_decimales - horas_enteras) * 60))

    if minutos_restantes == 60:
        horas_enteras += 1
        minutos_restantes = 0

    resultado = f"{horas_enteras} h y {minutos_restantes} min"
    return f"- {resultado}" if negativo else resultado

def formatear_cronometro_detallado(segundos_totales):
    h = int(segundos_totales // 3600)
    m = int((segundos_totales % 3600) // 60)
    s = int(segundos_totales % 60)
    return f"{h} h : {m:02d} min : {s:02d} seg"

def parsear_horas_texto(valor):
    if pd.isnull(valor):
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)

    val_str = str(valor).lower().strip()
    try:
        if "h" in val_str or "min" in val_str:
            partes = val_str.replace(" y ", " ").split()
            h = 0.0
            m = 0.0
            for i, p in enumerate(partes):
                if "h" in p and i > 0:
                    h = float(partes[i - 1])
                elif "min" in p and i > 0:
                    m = float(partes[i - 1])
            return h + (m / 60.0)
        else:
            return float(val_str.replace(",", "."))
    except Exception:
        return 0.0

def obtener_dias_laborables_mes(anio, mes, laboral_dict):
    primero = datetime(anio, mes, 1)
    if mes == 12:
        siguiente = datetime(anio + 1, 1, 1)
    else:
        siguiente = datetime(anio, mes + 1, 1)
    
    laborables = 0
    curr = primero
    while curr < siguiente:
        f_str = curr.strftime("%d-%m-%Y")
        def_lab = curr.weekday() < 5
        es_lab = laboral_dict.get(f_str, def_lab)
        if es_lab:
            laborables += 1
        curr += timedelta(days=1)
    return max(laborables, 1)

def calcular_totales(diccionario_registros, laboral_dict, horas_cronometro_extra=0.0):
    hoy_calc = datetime.now()
    hoy_sin_hora = hoy_calc.replace(hour=0, minute=0, second=0, microsecond=0)
    hoy_str_calc = hoy_calc.strftime("%d-%m-%Y")

    total_hoy = diccionario_registros.get(hoy_str_calc, 0.0) + horas_cronometro_extra
    total_sem = 0.0
    total_mes = 0.0

    if hoy_calc.weekday() == 0:
        inicio_semana = hoy_sin_hora
    else:
        inicio_semana = hoy_sin_hora - timedelta(days=hoy_calc.weekday())
    fin_semana = hoy_calc

    inicio_mes = hoy_sin_hora.replace(day=1)
    fin_mes = hoy_calc

    for fecha_str, horas in diccionario_registros.items():
        try:
            fecha_dt = datetime.strptime(fecha_str, "%d-%m-%Y")
            if inicio_semana <= fecha_dt <= fin_semana:
                total_sem += horas
            if inicio_mes <= fecha_dt <= fin_mes:
                total_mes += horas
        except ValueError:
            pass

    total_sem += horas_cronometro_extra
    total_mes += horas_cronometro_extra

    ayer_sin_hora = hoy_sin_hora - timedelta(days=1)
    inicio_deuda = datetime(2026, 7, 22)

    horas_esperadas_hasta_ayer = 0.0
    curr = inicio_deuda
    while curr <= ayer_sin_hora:
        f_str = curr.strftime("%d-%m-%Y")
        def_lab = curr.weekday() < 5
        es_lab = laboral_dict.get(f_str, def_lab)
        
        if es_lab:
            dias_lab_mes = obtener_dias_laborables_mes(curr.year, curr.month, laboral_dict)
            horas_esperadas_hasta_ayer += 93.0 / dias_lab_mes
        curr += timedelta(days=1)

    horas_totales_trabajadas = sum(diccionario_registros.values())
    deuda = horas_esperadas_hasta_ayer - horas_totales_trabajadas

    def calcular_deuda_mes(inicio_mes_dt, fin_mes_dt):
        d_lab = 0.0
        h_trab = 0.0
        c = inicio_mes_dt
        limite = min(fin_mes_dt, ayer_sin_hora)
        while c <= limite:
            if c >= datetime(2026, 7, 22):
                f_str = c.strftime("%d-%m-%Y")
                def_lab = c.weekday() < 5
                es_lab = laboral_dict.get(f_str, def_lab)
                
                if es_lab:
                    dias_lab_mes = obtener_dias_laborables_mes(c.year, c.month, laboral_dict)
                    d_lab += 93.0 / dias_lab_mes
            h_trab += diccionario_registros.get(c.strftime("%d-%m-%Y"), 0.0)
            c += timedelta(days=1)
        return d_lab - h_trab

    deuda_julio = calcular_deuda_mes(datetime(2026, 7, 22), datetime(2026, 7, 31))
    deuda_agosto = calcular_deuda_mes(datetime(2026, 8, 1), datetime(2026, 8, 31))
    deuda_septiembre = calcular_deuda_mes(datetime(2026, 9, 1), datetime(2026, 9, 30))
    deuda_octubre = calcular_deuda_mes(datetime(2026, 10, 1), datetime(2026, 10, 31))

    horas_totales_obligatorio = 0.0
    c_tot = inicio_deuda
    while c_tot <= ayer_sin_hora:
        f_str = c_tot.strftime("%d-%m-%Y")
        def_lab = c_tot.weekday() < 5
        es_lab = laboral_dict.get(f_str, def_lab)
        
        if es_lab:
            dias_lab_mes = obtener_dias_laborables_mes(c_tot.year, c_tot.month, laboral_dict)
            horas_totales_obligatorio += 93.0 / dias_lab_mes
        c_tot += timedelta(days=1)

    return (
        round(total_hoy, 2),
        round(total_sem, 2),
        round(total_mes, 2),
        round(deuda, 2),
        inicio_semana,
        inicio_mes,
        round(deuda_julio, 2),
        round(deuda_agosto, 2),
        round(deuda_septiembre, 2),
        round(deuda_octubre, 2),
        round(horas_totales_obligatorio, 2),
        round(horas_totales_trabajadas, 2),
    )

def guardar_todo_en_sheet(diccionario_registros, diccionario_laboral):
    try:
        worksheet.clear()
        datos_para_guardar = [["Fecha", "Horas", "Laboral"]]
        
        # Ordenar estrictamente por fecha cronológica antes de volcar al Sheet
        fechas_ordenadas = sorted(
            diccionario_registros.keys(),
            key=lambda x: datetime.strptime(x, "%d-%m-%Y")
        )
        
        for fec in fechas_ordenadas:
            fecha_como_texto = f"'{fec}"
            val_h = float(diccionario_registros[fec])
            
            # Obtener estado laboral asegurando fin de semana por defecto falso
            dt_temp = datetime.strptime(fec, "%d-%m-%Y")
            def_lab = dt_temp.weekday() < 5
            val_l = str(diccionario_laboral.get(fec, def_lab))
            
            datos_para_guardar.append([fecha_como_texto, val_h, val_l])

        worksheet.append_rows(datos_para_guardar, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        st.error(f"Error al sincronizar con Google Sheets: {e}")
        return False

def actualizar_fila_en_sheet(fecha_fec, nueva_hora, es_laboral):
    reg_actual, lab_actual = obtener_datos_hoja()
    reg_actual[fecha_fec] = nueva_hora
    lab_actual[fecha_fec] = es_laboral
    return guardar_todo_en_sheet(reg_actual, lab_actual)

def generar_pie_chart(actual, objetivo, color_faltante="#3b82f6"):
    fig, ax = plt.subplots(figsize=(2.2, 2.2))
    fig.patch.set_facecolor("none")
    ax.set_facecolor("none")

    if actual >= objetivo:
        exceso = actual - objetivo
        tamaños = [objetivo, exceso]
        colores = ["#334155", "#ec4899"]
    else:
        faltante = objetivo - actual
        tamaños = [actual, faltante]
        colores = ["#334155", color_faltante]

    ax.pie(
        tamaños,
        colors=colores,
        startangle=90,
        wedgeprops=dict(width=0.4, edgecolor="none"),
    )

    ax.set(aspect="equal")
    plt.tight_layout()
    return fig

# ------------------ INICIALIZACIÓN DE ESTADOS ------------------
hoy = datetime.now()
hoy_str = hoy.strftime("%d-%m-%Y")

if "registros" not in st.session_state or "laboral" not in st.session_state:
    reg, lab = obtener_datos_hoja()
    st.session_state["registros"] = reg
    st.session_state["laboral"] = lab

if "cronometro_activo" not in st.session_state:
    st.session_state["cronometro_activo"] = False

if "tiempo_inicio" not in st.session_state:
    st.session_state["tiempo_inicio"] = None

if "segundos_acumulados" not in st.session_state:
    st.session_state["segundos_acumulados"] = 0

registros_actuales = st.session_state["registros"]
laboral_actuales = st.session_state["laboral"]

segundos_totales_crono = st.session_state["segundos_acumulados"]
if st.session_state["cronometro_activo"] and st.session_state["tiempo_inicio"]:
    diferencia = datetime.now() - st.session_state["tiempo_inicio"]
    segundos_totales_crono += int(diferencia.total_seconds())

horas_cronometro_decimales = segundos_totales_crono / 3600.0

(
    tot_hoy,
    tot_sem,
    tot_mes,
    deuda_horas,
    inicio_sem_dt,
    inicio_mes_dt,
    deuda_julio,
    deuda_agosto,
    deuda_septiembre,
    deuda_octubre,
    horas_totales_obligatorio,
    horas_totales_trabajadas,
) = calcular_totales(registros_actuales, laboral_actuales, 0.0)

# ------------------ TÍTULO PRINCIPAL DE LA WEB ------------------
st.title("Control horas work")

if st.button("🔄 Recargar datos de Google Sheets"):
    reg, lab = obtener_datos_hoja()
    st.session_state["registros"] = reg
    st.session_state["laboral"] = lab
    st.rerun()

st.markdown("---")

# ------------------ DISEÑO GENERAL DE LA INTERFAZ (2 COLUMNAS) ------------------
col_izq, col_der = st.columns([1.1, 0.9])

with col_izq:
    # --- 1. CRONÓMETRO Y REGISTRO ---
    st.markdown("### Cronómetro y Registro de Horas")
    with st.container(border=True):
        
        placeholder_crono = st.empty()
        placeholder_crono.markdown(f"### ⏱️ {formatear_cronometro_detallado(segundos_totales_crono)}")
        
        c_btn1, c_btn2, c_btn3 = st.columns(3)
        with c_btn1:
            if not st.session_state["cronometro_activo"]:
                if st.button("Activar", use_container_width=True, type="primary"):
                    st.session_state["cronometro_activo"] = True
                    st.session_state["tiempo_inicio"] = datetime.now()
                    st.rerun()
            else:
                if st.button("Pausar", use_container_width=True):
                    st.session_state["segundos_acumulados"] = segundos_totales_crono
                    st.session_state["cronometro_activo"] = False
                    st.session_state["tiempo_inicio"] = None
                    st.rerun()
        with c_btn2:
            if st.button("Resetear", use_container_width=True):
                st.session_state["cronometro_activo"] = False
                st.session_state["tiempo_inicio"] = None
                st.session_state["segundos_acumulados"] = 0
                st.rerun()
        with c_btn3:
            btn_registrar_cron = st.button("Registrar crono", use_container_width=True, type="secondary")

        if btn_registrar_cron:
            if horas_cronometro_decimales > 0:
                fec = hoy_str
                horas_a_sumar = round(horas_cronometro_decimales, 2)

                if fec in st.session_state["registros"]:
                    st.session_state["registros"][fec] += horas_a_sumar
                else:
                    st.session_state["registros"][fec] = horas_a_sumar

                def_lab = hoy.weekday() < 5
                es_lab_actual = laboral_actuales.get(fec, def_lab)
                actualizar_fila_en_sheet(fec, st.session_state["registros"][fec], es_lab_actual)
                
                st.session_state["cronometro_activo"] = False
                st.session_state["tiempo_inicio"] = None
                st.session_state["segundos_acumulados"] = 0

                st.success(f"¡Registradas {formatear_horas(horas_a_sumar)} al día de hoy con éxito!")
                st.rerun()
            else:
                st.warning("El cronómetro está a 0; no hay tiempo que registrar.")

        st.markdown("---")
        st.write("**O ingresar horas manualmente:**")
        col_reg1, col_reg2, col_reg3, col_reg4 = st.columns([1.2, 0.9, 0.9, 1.0])
        with col_reg1:
            input_fecha = st.text_input("Fecha (DD-MM-YYYY):", value=hoy_str)
        with col_reg2:
            input_horas = st.number_input("Horas:", min_value=0, value=0, step=1)
        with col_reg3:
            input_minutos = st.number_input("Minutos:", min_value=0, max_value=59, value=0, step=1)
        with col_reg4:
            st.write("")
            st.write("")
            btn_guardar = st.button("Registrar", use_container_width=True)

        if btn_guardar:
            horas_nuevas = round(input_horas + (input_minutos / 60), 2)
            fec = limpiar_fecha(input_fecha)

            if horas_nuevas > 0:
                if fec in st.session_state["registros"]:
                    st.session_state["registros"][fec] += horas_nuevas
                else:
                    st.session_state["registros"][fec] = horas_nuevas

                try:
                    dt_temp = datetime.strptime(fec, "%d-%m-%Y")
                    def_lab = dt_temp.weekday() < 5
                except:
                    def_lab = True
                es_lab_actual = laboral_actuales.get(fec, def_lab)
                
                actualizar_fila_en_sheet(fec, st.session_state["registros"][fec], es_lab_actual)
                st.success("¡Horas manuales guardadas correctamente!")
                st.rerun()
            else:
                st.warning("Introduce una cantidad de horas válida.")

    st.markdown("---")

    # --- 2. RESUMEN ACTUAL ---
    st.markdown("### Resumen actual")
    col1, col2, col3 = st.columns(3)

    dia_hoy_nombre = dias_semana_lower[hoy.weekday()]
    mes_hoy_nombre = meses_espanol_lower[hoy.month]

    # Tarjeta Hoy
    with col1:
        def_lab_hoy = hoy.weekday() < 5
        es_laboral_hoy = laboral_actuales.get(hoy_str, def_lab_hoy)
        
        if not es_laboral_hoy:
            base_comparativa_hoy = 4.0
            horas_efectivas_hoy = max(tot_hoy, 4.0) if tot_hoy > 0 else 4.0
            progreso_hoy = min(max(horas_efectivas_hoy / base_comparativa_hoy, 0.0), 1.0)
            if tot_hoy > 4.0:
                progreso_hoy = 1.0
            texto_progreso = f"Día no laborable: {int(max(tot_hoy / 4.0, 1.0) * 100)}%"
        else:
            progreso_hoy = min(max(tot_hoy / 4.0, 0.0), 1.0)
            texto_progreso = f"Objetivo diario: {int(progreso_hoy * 100)}%"

        st.progress(progreso_hoy, text=texto_progreso)

        with st.container(border=True):
            st.metric("Hoy", formatear_horas(tot_hoy))
            st.caption(f"{dia_hoy_nombre} {hoy.day} de {mes_hoy_nombre}")

        valor_pie_hoy = max(tot_hoy, 4.0) if not es_laboral_hoy else tot_hoy
        fig_hoy = generar_pie_chart(valor_pie_hoy, 4.0, color_faltante="#3b82f6")
        st.pyplot(fig_hoy, use_container_width=True)

    # Tarjeta Semana
    with col2:
        progreso_sem = min(max(tot_sem / 23.0, 0.0), 1.0)
        st.progress(progreso_sem, text=f"Objetivo semanal: {int(progreso_sem * 100)}%")

        with st.container(border=True):
            st.metric("Semana", formatear_horas(tot_sem))
            dia_sem_nombre = dias_semana_lower[inicio_sem_dt.weekday()]
            mes_sem_nombre = meses_espanol_lower[inicio_sem_dt.month]
            st.caption(f"Contando desde el {dia_sem_nombre} {inicio_sem_dt.day} de {mes_sem_nombre}")

            with st.popover("detalles"):
                st.markdown("**Desglose de esta semana:**")
                curr = inicio_sem_dt
                while curr <= hoy:
                    f_str = curr.strftime("%d-%m-%Y")
                    h_dia = registros_actuales.get(f_str, 0.0)
                    d_nombre = dias_semana_lower[curr.weekday()].replace(" - ", "")
                    st.write(f"• **{d_nombre.capitalize()} {curr.day}:** {formatear_horas(h_dia)}")
                    curr += timedelta(days=1)

        fig_sem = generar_pie_chart(tot_sem, 23.0, color_faltante="#3b82f6")
        st.pyplot(fig_sem, use_container_width=True)

    # Tarjeta Mes
    with col3:
        progreso_mes = min(max(tot_mes / 93.0, 0.0), 1.0)
        st.progress(progreso_mes, text=f"Objetivo mensual: {int(progreso_mes * 100)}%")

        with st.container(border=True):
            st.metric("Mes", formatear_horas(tot_mes))
            dia_inicio_mes_nombre = dias_semana_lower[inicio_mes_dt.weekday()]
            mes_mes_nombre = meses_espanol_lower[inicio_mes_dt.month]
            st.caption(f"Contando desde el {dia_inicio_mes_nombre} 1 de {mes_mes_nombre}")

            with st.popover("detalles"):
                st.markdown(f"**Semanas de {meses_espanol[hoy.month]}:**")
                curr = inicio_mes_dt
                semana_num = 1
                while curr <= hoy:
                    dias_hasta_domingo = (6 - curr.weekday()) % 7
                    fin_semana_actual = curr + timedelta(days=dias_hasta_domingo)
                    if fin_semana_actual > hoy:
                        fin_semana_actual = hoy

                    horas_semana_bloque = 0.0
                    temp = curr
                    while temp <= fin_semana_actual:
                        h_val = registros_actuales.get(temp.strftime("%d-%m-%Y"), 0.0)
                        horas_semana_bloque += h_val
                        temp += timedelta(days=1)

                    st.write(
                        f"• **Semana {semana_num}** ({curr.day}/{curr.month} - "
                        f"{fin_semana_actual.day}/{fin_semana_actual.month}): "
                        f"**{formatear_horas(horas_semana_bloque)}**"
                    )

                    curr = fin_semana_actual + timedelta(days=1)
                    semana_num += 1

        fig_mes = generar_pie_chart(tot_mes, 93.0, color_faltante="#3b82f6")
        st.pyplot(fig_mes, use_container_width=True)

with col_der:
    # --- 3. APARTADO DE DEUDA ---
    st.markdown("### Horas a recuperar")

    if horas_totales_obligatorio > 0:
        porcentaje_progreso_deuda = min(max(horas_totales_trabajadas / horas_totales_obligatorio, 0.0), 1.0)
    else:
        porcentaje_progreso_deuda = 0.0

    st.progress(
        porcentaje_progreso_deuda,
        text=f"Progreso global de horas trabajadas: {int(porcentaje_progreso_deuda * 100)}% (Trabajadas: {formatear_horas(horas_totales_trabajadas)} / Obligatorias: {formatear_horas(horas_totales_obligatorio)})",
    )

    with st.container(border=True):
        st.metric("Total de horas pendientes de recuperar", formatear_horas(deuda_horas))
        st.caption("Cálculo basado en objetivo de 93h/mes (excluyendo días no laborables marcados) desde el 22 de Julio. Las horas trabajadas antes de esa fecha y en días no laborables restan deuda.")

        with st.popover("detalles de deuda"):
            st.markdown("**Deuda acumulada por mes (hasta ayer):**")
            st.write(f"• **Julio (desde 22):** {formatear_horas(deuda_julio)}")
            st.write(f"• **Agosto:** {formatear_horas(deuda_agosto)}")
            st.write(f"• **Septiembre:** {formatear_horas(deuda_septiembre)}")
            st.write(f"• **Octubre:** {formatear_horas(deuda_octubre)}")

    st.markdown("---")

    # --- 4. TABLA DE HISTORIAL Y EDICIÓN ORDENADA CRONOLÓGICAMENTE ---
    st.subheader("Historial de Meses")

    lista_datos = []
    for f, h in registros_actuales.items():
        try:
            dt_t = datetime.strptime(f, "%d-%m-%Y")
            def_l = dt_t.weekday() < 5
        except:
            def_l = True
        is_l = laboral_actuales.get(f, def_l)
        lista_datos.append({"Fecha": f, "Horas": h, "Laboral": is_l})
        
    df_global = pd.DataFrame(lista_datos)

    if not df_global.empty:
        df_global["Fecha_dt"] = pd.to_datetime(df_global["Fecha"], format="%d-%m-%Y", errors="coerce")
    else:
        df_global["Fecha_dt"] = pd.Series(dtype="datetime64[ns]")
        df_global["Laboral"] = pd.Series(dtype="bool")

    # ORDEN CRONOLÓGICO ESTRICTO (tanto por año/mes como por día)
    df_global_asc = df_global.sort_values(by="Fecha_dt", ascending=True).copy()

    if not df_global_asc.empty:
        df_global_asc["Mes_ID"] = df_global_asc["Fecha_dt"].apply(
            lambda x: (x.year, x.month) if pd.notnull(x) else (0, 0)
        )
        df_global_asc["Mes_Nombre"] = df_global_asc["Fecha_dt"].apply(
            lambda x: f"{meses_espanol[x.month]} {x.year}" if pd.notnull(x) else "Desconocido"
        )
        
        # Obtener la lista única de meses ordenada cronológicamente (usando Mes_ID para asegurar orden de meses correcto)
        meses_unicos_df = df_global_asc.sort_values(by="Fecha_dt")[["Mes_ID", "Mes_Nombre"]].drop_duplicates()
        meses_unicos = meses_unicos_df["Mes_Nombre"].tolist()
    else:
        meses_unicos = []

    if meses_unicos:
        pestañas = st.tabs(meses_unicos)
        for i, mes_nombre in enumerate(meses_unicos):
            with pestañas[i]:
                df_mes = df_global_asc[df_global_asc["Mes_Nombre"] == mes_nombre][["Fecha", "Horas", "Laboral"]].reset_index(drop=True)

                total_horas_mes_actual = df_mes["Horas"].sum()

                st.info(f"Total horas trabajadas en {mes_nombre}: {formatear_horas(total_horas_mes_actual)}")
                st.write(f"Editando registros de: **{mes_nombre}**")

                df_mes_visual = df_mes.copy()
                df_mes_visual["Fecha"] = df_mes_visual["Fecha"].apply(fecha_a_formato_humano)
                df_mes_visual["Horas"] = df_mes_visual["Horas"].apply(formatear_horas)

                df_editado = st.data_editor(
                    df_mes_visual,
                    key=f"editor_mes_{i}_{mes_nombre}",
                    use_container_width=True,
                    hide_index=True,
                    height=280,
                )

                if not df_editado.equals(df_mes_visual):
                    fechas_convertidas = df_editado["Fecha"].apply(formato_humano_a_fecha)
                    df_global_asc.loc[df_global_asc["Mes_Nombre"] == mes_nombre, "Fecha"] = fechas_convertidas.values
                    df_global_asc.loc[df_global_asc["Mes_Nombre"] == mes_nombre, "Horas"] = df_editado["Horas"].apply(parsear_horas_texto).values
                    df_global_asc.loc[df_global_asc["Mes_Nombre"] == mes_nombre, "Laboral"] = df_editado["Laboral"].values

                    nuevo_diccionario_reg = {}
                    nuevo_diccionario_lab = {}
                    for _, r in df_global_asc.iterrows():
                        fec_limpia = limpiar_fecha(r["Fecha"])
                        val_horas = parsear_horas_texto(r["Horas"])
                        val_lab = bool(r["Laboral"])
                        if fec_limpia:
                            nuevo_diccionario_reg[fec_limpia] = val_horas
                            nuevo_diccionario_lab[fec_limpia] = val_lab

                    guardar_todo_en_sheet(nuevo_diccionario_reg, nuevo_diccionario_lab)
                    st.session_state["registros"] = nuevo_diccionario_reg
                    st.session_state["laboral"] = nuevo_diccionario_lab

                    st.success("Se han guardado los cambios y ordenado cronológicamente.")
                    st.rerun()
    else:
        st.info("No hay registros todavía.")

# ------------------ BUCLE DE ACTUALIZACIÓN EN TIEMPO REAL ------------------
if st.session_state["cronometro_activo"]:
    time.sleep(1)
    st.rerun()
