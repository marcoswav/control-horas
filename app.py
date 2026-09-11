from datetime import datetime, timedelta
import gspread
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
        /* Forzar misma altura en los contenedores del resumen actual */
        div[data-testid="stVerticalBlock"] > div[data-testid="stContainer"] {
            height: 195px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        
        /* Degradado azul para progreso normal (más rápido: 1.5s) */
        div[data-testid="stProgress"] > div > div > div {
            background-image: linear-gradient(90deg, #3b82f6, #1d4ed8, #60a5fa);
            background-size: 200% 100%;
            animation: gradientAnimation 1.5s ease infinite;
            transition: width 0.6s ease-in-out;
        }

        /* Degradado rosa para cuando el objetivo está completado (100% o más) */
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
credenciales_dict = dict(st.secrets["gcp_service_account"])
gc = gspread.service_account_from_dict(credenciales_dict)

sh = gc.open("stock control horas")
worksheet = sh.get_worksheet(0)

# ------------------ DICCIONARIOS Y FUNCIONES ------------------
meses_espanol = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}

meses_espanol_lower = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}

dias_semana_lower = {
    0: "L - ",
    1: "M - ",
    2: "X - ",
    3: "J - ",
    4: "V - ",
    5: "S - ",
    6: "D - ",
}


def limpiar_fecha(fec_str):
    fec_str = str(fec_str).strip()
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
        registros = worksheet.get_all_records()
    except Exception:
        return {}

    diccionario_registros = {}
    for fila in registros:
        fecha_raw = fila.get("Fecha", "")
        fecha = limpiar_fecha(fecha_raw)
        if not fecha or fecha == "Fecha":
            continue

        raw_horas = fila.get("Horas", 0)
        try:
            horas = float(raw_horas) if str(raw_horas).strip() != "" else 0.0
        except ValueError:
            horas = 0.0

        if fecha in diccionario_registros:
            diccionario_registros[fecha] += horas
        else:
            diccionario_registros[fecha] = horas

    return diccionario_registros


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
            return float(val_str)
    except Exception:
        return 0.0


def calcular_totales(diccionario_registros):
    hoy_calc = datetime.now()
    hoy_sin_hora = hoy_calc.replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    hoy_str_calc = hoy_calc.strftime("%d-%m-%Y")

    total_hoy = diccionario_registros.get(hoy_str_calc, 0.0)
    total_mes = 0.0
    total_semana = 0.0

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
                total_semana += horas
            if inicio_mes <= fecha_dt <= fin_mes:
                total_mes += horas
        except ValueError:
            pass

    ayer_sin_hora = hoy_sin_hora - timedelta(days=1)
    inicio_deuda = datetime(2026, 7, 16)

    # Cálculo de horas esperadas (solo de Lunes a Viernes) y horas trabajadas (todos los días hasta ayer)
    horas_esperadas_hasta_ayer = 0.0
    curr = inicio_deuda
    while curr <= ayer_sin_hora:
        if curr.weekday() < 5:  # Solo de lunes a viernes se genera objetivo/obligación
            horas_esperadas_hasta_ayer += 23.0 / 5.0
        curr += timedelta(days=1)

    horas_trabajadas_hasta_ayer = 0.0
    for fecha_str, horas in diccionario_registros.items():
        try:
            fecha_dt = datetime.strptime(fecha_str, "%d-%m-%Y")
            if inicio_deuda <= fecha_dt <= ayer_sin_hora:
                horas_trabajadas_hasta_ayer += horas  # Cuenta cualquier día (incluyendo fines de semana) para reducir la deuda
        except ValueError:
            pass

    deuda = horas_esperadas_hasta_ayer - horas_trabajadas_hasta_ayer

    def calcular_deuda_mes(inicio_mes_dt, fin_mes_dt):
        d_lab = 0.0
        h_trab = 0.0
        c = inicio_mes_dt
        limite = min(fin_mes_dt, ayer_sin_hora)
        while c <= limite:
            if c >= datetime(2026, 7, 16):
                if c.weekday() < 5:
                    d_lab += 23.0 / 5.0
                h_trab += diccionario_registros.get(c.strftime("%d-%m-%Y"), 0.0)
            c += timedelta(days=1)
        return d_lab - h_trab

    deuda_julio = calcular_deuda_mes(datetime(2026, 7, 16), datetime(2026, 7, 31))
    deuda_agosto = calcular_deuda_mes(datetime(2026, 8, 1), datetime(2026, 8, 31))
    deuda_septiembre = calcular_deuda_mes(datetime(2026, 9, 1), ayer_sin_hora)

    return (
        round(total_hoy, 2),
        round(total_semana, 2),
        round(total_mes, 2),
        round(deuda, 2),
        inicio_semana,
        inicio_mes,
        round(deuda_julio, 2),
        round(deuda_agosto, 2),
        round(deuda_septiembre, 2),
    )


def actualizar_fila_en_sheet(fecha_fec, nueva_hora):
    try:
        filas = worksheet.get_all_values()
        fecha_como_texto = f"'{fecha_fec}"

        if not filas:
            worksheet.append_row(
                ["Fecha", "Horas"], value_input_option="USER_ENTERED"
            )
            worksheet.append_row(
                [fecha_como_texto, float(nueva_hora)], value_input_option="USER_ENTERED"
            )
            return True

        encontrado = False
        for i, fila in enumerate(filas[1:], start=2):
            if fila and limpiar_fecha(fila[0]) == fecha_fec:
                worksheet.update_cell(i, 1, fecha_como_texto)
                worksheet.update_cell(i, 2, float(nueva_hora))
                encontrado = True
                break

        if not encontrado:
            worksheet.append_row(
                [fecha_como_texto, float(nueva_hora)], value_input_option="USER_ENTERED"
            )

        return True
    except Exception as e:
        st.error(f"Error al actualizar la hoja: {e}")
        return False


def guardar_todo_en_sheet(diccionario_registros):
    try:
        worksheet.clear()
        datos_para_guardar = [["Fecha", "Horas"]]
        for fec in sorted(diccionario_registros.keys()):
            fecha_como_texto = f"'{fec}"
            datos_para_guardar.append(
                [fecha_como_texto, float(diccionario_registros[fec])]
            )

        worksheet.append_rows(datos_para_guardar, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        st.error(f"Error al sincronizar con Google Sheets: {e}")
        return False


# ------------------ INICIALIZACIÓN DE FECHA Y ESTADO ------------------
hoy = datetime.now()
hoy_str = hoy.strftime("%d-%m-%Y")

if "registros" not in st.session_state:
    st.session_state["registros"] = obtener_datos_hoja()

registros_actuales = st.session_state["registros"]
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
) = calcular_totales(registros_actuales)

# ------------------ DISEÑO GENERAL DE LA INTERFAZ ------------------
col_izq, col_der = st.columns([1.1, 0.9])

with col_izq:
    st.title("Control horas work")

    # --- RESUMEN ACTUAL ---
    st.markdown("### rezumen actual")
    col1, col2, col3 = st.columns(3)

    dia_hoy_nombre = dias_semana_lower[hoy.weekday()]
    mes_hoy_nombre = meses_espanol_lower[hoy.month]

    # 1. Tarjeta Hoy
    with col1:
        progreso_hoy = min(max(tot_hoy / 4.0, 0.0), 1.0)
        st.progress(
            progreso_hoy, text=f"Objetivo diario: {int(progreso_hoy * 100)}%"
        )
        with st.container(border=True):
            st.metric("Hoy", formatear_horas(tot_hoy))
            st.caption(f"{dia_hoy_nombre} {hoy.day} de {mes_hoy_nombre}")

    # 2. Tarjeta Semana
    with col2:
        progreso_sem = min(max(tot_sem / 23.0, 0.0), 1.0)
        st.progress(
            progreso_sem, text=f"Objetivo semanal: {int(progreso_sem * 100)}%"
        )
        with st.container(border=True):
            st.metric("Semana", formatear_horas(tot_sem))
            dia_sem_nombre = dias_semana_lower[inicio_sem_dt.weekday()]
            mes_sem_nombre = meses_espanol_lower[inicio_sem_dt.month]
            st.caption(
                f"Contando desde el {dia_sem_nombre} {inicio_sem_dt.day}"
                f" de {mes_sem_nombre}"
            )

            with st.popover("detalles"):
                st.markdown("**Desglose de esta semana:**")
                curr = inicio_sem_dt
                while curr <= hoy:
                    f_str = curr.strftime("%d-%m-%Y")
                    h_dia = registros_actuales.get(f_str, 0.0)
                    d_nombre = dias_semana_lower[curr.weekday()].replace(" - ", "")
                    st.write(
                        f"• **{d_nombre.capitalize()} {curr.day}:**"
                        f" {formatear_horas(h_dia)}"
                    )
                    curr += timedelta(days=1)

    # 3. Tarjeta Mes
    with col3:
        progreso_mes = min(max(tot_mes / 92.0, 0.0), 1.0)
        st.progress(
            progreso_mes, text=f"Objetivo mensual: {int(progreso_mes * 100)}%"
        )
        with st.container(border=True):
            st.metric("Mes", formatear_horas(tot_mes))
            dia_inicio_mes_nombre = dias_semana_lower[inicio_mes_dt.weekday()]
            mes_mes_nombre = meses_espanol_lower[inicio_mes_dt.month]
            st.caption(
                f"Contando desde el {dia_inicio_mes_nombre} 1 de {mes_mes_nombre}"
            )

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
                        horas_semana_bloque += registros_actuales.get(
                            temp.strftime("%d-%m-%Y"), 0.0
                        )
                        temp += timedelta(days=1)

                    st.write(
                        f"• **Semana {semana_num}** ({curr.day}/{curr.month} - "
                        f"{fin_semana_actual.day}/{fin_semana_actual.month}): "
                        f"**{formatear_horas(horas_semana_bloque)}**"
                    )

                    curr = fin_semana_actual + timedelta(days=1)
                    semana_num += 1

    st.markdown("---")

    # --- REGISTRAR NUEVAS HORAS ---
    st.markdown("### Registrar horas workeadas")
    input_fecha = st.text_input("Fecha (DD-MM-YYYY):", value=hoy_str)

    col_h, col_m = st.columns(2)
    with col_h:
        input_horas = st.number_input("Horas enteras:", min_value=0, value=4, step=1)
    with col_m:
        input_minutos = st.number_input(
            "Minutos extra:", min_value=0, max_value=59, value=0, step=1
        )

    if st.button("Guardar en Google Drive", type="primary"):
        horas_nuevas = round(input_horas + (input_minutos / 60), 2)
        fec = limpiar_fecha(input_fecha)

        if fec in st.session_state["registros"]:
            st.session_state["registros"][fec] += horas_nuevas
        else:
            st.session_state["registros"][fec] = horas_nuevas

        actualizar_fila_en_sheet(fec, st.session_state["registros"][fec])

        (
            tot_hoy_nuevo,
            tot_sem_nuevo,
            tot_mes_nuevo,
            deuda_nueva,
            _,
            _,
            _,
            _,
            _,
        ) = calcular_totales(st.session_state["registros"])

        st.success(
            f"guardao!\n\n"
            f"- **Total Hoy:** {formatear_horas(tot_hoy_nuevo)}\n"
            f"- **Total Esta Semana:** {formatear_horas(tot_sem_nuevo)}\n"
            f"- **Total Este Mes:** {formatear_horas(tot_mes_nuevo)}\n"
            f"- **Deuda Actual:** {formatear_horas(deuda_nueva)}"
        )
        st.rerun()

with col_der:
    # --- TABLA DE HISTORIAL Y EDICIÓN ---
    st.subheader("Horas workeadas anteriormente")

    if registros_actuales:
        lista_datos = [
            {"Fecha": f, "Horas": h} for f, h in registros_actuales.items()
        ]
        df_global = pd.DataFrame(lista_datos)

        df_global["Fecha_dt"] = pd.to_datetime(
            df_global["Fecha"], format="%d-%m-%Y", errors="coerce"
        )

        df_global["Mes"] = df_global["Fecha_dt"].apply(
            lambda x: (
                f"{meses_espanol[x.month]} {x.year}"
                if pd.notnull(x)
                else "Desconocido"
            )
        )

        df_global_desc = df_global.sort_values(by="Fecha_dt", ascending=False)
        meses_disponibles = []
        for m in df_global_desc["Mes"]:
            if m not in meses_disponibles:
                meses_disponibles.append(m)

        df_global_asc = df_global.sort_values(by="Fecha_dt", ascending=True)
        df_global_asc = df_global_asc.drop(columns=["Fecha_dt"])

        if meses_disponibles:
            pestañas = st.tabs(meses_disponibles)

            for i, mes_nombre in enumerate(meses_disponibles):
                with pestañas[i]:
                    st.write(f"Editando registros de: **{mes_nombre}**")

                    df_mes = df_global_asc[df_global_asc["Mes"] == mes_nombre][
                        ["Fecha", "Horas"]
                    ].reset_index(drop=True)

                    df_mes_visual = df_mes.copy()
                    df_mes_visual["Fecha"] = df_mes_visual["Fecha"].apply(
                        fecha_a_formato_humano
                    )
                    df_mes_visual["Horas"] = df_mes_visual["Horas"].apply(formatear_horas)

                    df_editado = st.data_editor(
                        df_mes_visual,
                        key=f"editor_{i}_{mes_nombre}",
                        use_container_width=True,
                        hide_index=True,
                        height=280,
                    )

                    if not df_editado.equals(df_mes_visual):
                        fechas_convertidas = df_editado["Fecha"].apply(
                            formato_humano_a_fecha
                        )
                        df_global_asc.loc[df_global_asc["Mes"] == mes_nombre, "Fecha"] = (
                            fechas_convertidas.values
                        )
                        df_global_asc.loc[df_global_asc["Mes"] == mes_nombre, "Horas"] = (
                            df_editado["Horas"].apply(parsear_horas_texto).values
                        )

                        df_para_guardar = df_global_asc[["Fecha", "Horas"]]

                        nuevo_diccionario = {}
                        for _, r in df_para_guardar.iterrows():
                            fec_limpia = limpiar_fecha(r["Fecha"])
                            val_horas = parsear_horas_texto(r["Horas"])
                            nuevo_diccionario[fec_limpia] = val_horas

                        guardar_todo_en_sheet(nuevo_diccionario)

                        st.session_state["registros"] = nuevo_diccionario

                        st.success("se han guardao los cambios")
                        st.rerun()
    else:
        st.info("Aún no hay registros en la base de datos.")

    st.markdown("---")
    st.markdown("### Horas a recuperar")
    st.metric(
        "Total de horas a recuperar (Objetivo: 23h/sem de L a V, un día de retraso)",
        formatear_horas(deuda_horas),
    )
    st.caption(
        "Horas acumuladas pendientes de recuperar hasta ayer (reparte 23h entre"
        " los 5 días laborables de la semana, excluyendo fines de semana para la"
        " obligación pero restando si trabajas en ellos)."
    )

    with st.popover("detalles"):
        st.markdown("**Deuda acumulada por mes (hasta ayer):**")
        st.write(f"• **Julio (desde 16):** {formatear_horas(deuda_julio)}")
        st.write(f"• **Agosto:** {formatear_horas(deuda_agosto)}")
        st.write(f"• **Septiembre:** {formatear_horas(deuda_septiembre)}")
