from datetime import datetime, timedelta
import gspread
import pandas as pd
import streamlit as st

# Configuración de la página en ancho ampliado para las dos columnas
st.set_page_config(
    page_title="Gestor de Horas", page_icon="🕒", layout="wide"
)

# ------------------ CONEXIÓN CON GOOGLE SHEETS ------------------
credenciales_dict = dict(st.secrets["gcp_service_account"])
gc = gspread.service_account_from_dict(credenciales_dict)

# Conexión buscando el archivo en minúsculas
sh = gc.open("stock control horas")
worksheet = sh.get_worksheet(0)


# ------------------ FUNCIONES LÓGICAS ------------------
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
  """Convierte un número decimal a formato legible de horas y minutos."""
  if total_decimales < 0:
    total_decimales = 0.0
  horas_enteras = int(total_decimales)
  minutos_restantes = int(round((total_decimales - horas_enteras) * 60))

  if minutos_restantes == 60:
    horas_enteras += 1
    minutos_restantes = 0

  return f"{horas_enteras} h y {minutos_restantes} min"


def calcular_totales(diccionario_registros):
  hoy = datetime.now()
  hoy_sin_hora = hoy.replace(hour=0, minute=0, second=0, microsecond=0)
  hoy_str = hoy.strftime("%d-%m-%Y")

  total_hoy = diccionario_registros.get(hoy_str, 0.0)
  total_mes = 0.0
  total_semana = 0.0

  # Semana: desde el último lunes hasta hoy (si es lunes, solo hoy)
  if hoy.weekday() == 0:
    inicio_semana = hoy_sin_hora
  else:
    inicio_semana = hoy_sin_hora - timedelta(days=hoy.weekday())
  fin_semana = hoy

  # Mes: desde el día 1 del mes actual hasta hoy
  inicio_mes = hoy_sin_hora.replace(day=1)
  fin_mes = hoy

  dias_semana = []
  dias_mes = []

  for fecha_str, horas in diccionario_registros.items():
    try:
      fecha_dt = datetime.strptime(fecha_str, "%d-%m-%Y")
      if inicio_semana <= fecha_dt <= fin_semana:
        total_semana += horas
        dias_semana.append(fecha_str)
      if inicio_mes <= fecha_dt <= fin_mes:
        total_mes += horas
        dias_mes.append(fecha_str)
    except ValueError:
      pass

  dias_semana = sorted(
      dias_semana, key=lambda x: datetime.strptime(x, "%d-%m-%Y")
  )
  dias_mes = sorted(dias_mes, key=lambda x: datetime.strptime(x, "%d-%m-%Y"))

  return (
      round(total_hoy, 2),
      round(total_semana, 2),
      round(total_mes, 2),
      dias_semana,
      dias_mes,
  )


def sincronizar_dataframe_a_sheet(df_completo):
  """Vuelca los datos del DataFrame editado de vuelta a Google Sheets."""
  try:
    lote = [["Fecha", "Horas"]]
    for _, row in df_completo.iterrows():
      lote.append([str(row["Fecha"]), float(row["Horas"])])

    worksheet.clear()
    worksheet.update(lote)
    return True
  except Exception as e:
    st.error(f"Error al sincronizar con Google Drive: {e}")
    return False


# ------------------ OBTENCIÓN DE DATOS INICIALES ------------------
hoy_str = datetime.now().strftime("%d-%m-%Y")
registros_actuales = obtener_datos_hoja()
tot_hoy, tot_sem, tot_mes, dias_sem, dias_m = calcular_totales(
    registros_actuales
)

# Diccionario para nombres de meses en español
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

# ------------------ DISEÑO GENERAL DE LA INTERFAZ ------------------
col_izq, col_der = st.columns([1, 1.2])

with col_izq:
  st.title("🕒 Gestor de Horas")

  # --- RESUMEN ACTUAL ---
  st.markdown("### 📊 Resumen Actual")
  col1, col2, col3 = st.columns(3)

  with col1:
    st.metric("Hoy", formatear_horas(tot_hoy))
    st.caption(f"Día: {hoy_str}")

  with col2:
    st.metric("Esta Semana", formatear_horas(tot_sem))
    if dias_sem:
      st.caption(f"Días: {', '.join(dias_sem)}")
    else:
      st.caption("Sin registros")

  with col3:
    st.metric("Este Mes", formatear_horas(tot_mes))
    if dias_m:
      st.caption(f"Días: {', '.join(dias_m)}")
    else:
      st.caption("Sin registros")

  st.markdown("---")

  # --- REGISTRAR NUEVAS HORAS (DEBAJO DEL RESUMEN) ---
  st.subheader("Registrar Horas")
  input_fecha = st.text_input("Fecha (DD-MM-YYYY):", value=hoy_str)

  col_h, col_m = st.columns(2)
  with col_h:
    input_horas = st.number_input("Horas enteras:", min_value=0, value=8, step=1)
  with col_m:
    input_minutos = st.number_input(
        "Minutos extra:", min_value=0, max_value=59, value=0, step=1
    )

  if st.button("Guardar en Google Drive", type="primary"):
    horas_nuevas = round(input_horas + (input_minutos / 60), 2)
    fec = limpiar_fecha(input_fecha)

    try:
      columna_fechas_raw = worksheet.col_values(1)
    except Exception:
      columna_fechas_raw = []

    encontrado = False
    fila_encontrada = -1

    for idx, val in enumerate(columna_fechas_raw[1:], start=2):
      if limpiar_fecha(val) == fec:
        encontrado = True
        fila_encontrada = idx
        break

    if encontrado:
      try:
        valor_previo = float(worksheet.cell(fila_encontrada, 2).value or 0)
      except ValueError:
        valor_previo = 0.0

      nuevo_total_dia = round(valor_previo + horas_nuevas, 2)
      worksheet.update_cell(fila_encontrada, 2, nuevo_total_dia)
    else:
      worksheet.append_row([fec, horas_nuevas])

    registros_actuales = obtener_datos_hoja()
    tot_hoy_nuevo, tot_sem_nuevo, tot_mes_nuevo, _, _ = calcular_totales(
        registros_actuales
    )

    st.success(
        f"✅ ¡Guardado con éxito!\n\n"
        f"- **Total Hoy:** {formatear_horas(tot_hoy_nuevo)}\n"
        f"- **Total Esta Semana:** {formatear_horas(tot_sem_nuevo)}\n"
        f"- **Total Este Mes:** {formatear_horas(tot_mes_nuevo)}"
    )

with col_der:
  # --- TABLA DE HISTORIAL Y EDICIÓN A LA DERECHA ---
  st.subheader("📋 Historial y Edición")

  if registros_actuales:
    lista_datos = [
        {"Fecha": f, "Horas": h} for f, h in registros_actuales.items()
    ]
    df_global = pd.DataFrame(lista_datos)

    df_global["Fecha_dt"] = pd.to_datetime(
        df_global["Fecha"], format="%d-%m-%Y", errors="coerce"
    )
    df_global = df_global.sort_values(by="Fecha_dt", ascending=True)

    df_global["Mes"] = df_global["Fecha_dt"].apply(
        lambda x: (
            f"{meses_espanol[x.month]} {x.year}"
            if pd.notnull(x)
            else "Desconocido"
        )
    )
    df_global = df_global.drop(columns=["Fecha_dt"])

    meses_disponibles = [str(m) for m in df_global["Mes"].unique().tolist()]

    # Poner el mes actual en primer lugar para que aparezca seleccionado por defecto
    mes_actual_nombre = (
        f"{meses_espanol[datetime.now().month]} {datetime.now().year}"
    )
    if mes_actual_nombre in meses_disponibles:
      meses_disponibles.remove(mes_actual_nombre)
      meses_disponibles.insert(0, mes_actual_nombre)

    if meses_disponibles:
      pestañas = st.tabs(meses_disponibles)

      for i, mes_nombre in enumerate(meses_disponibles):
        with pestañas[i]:
          st.write(f"Editando registros de: **{mes_nombre}**")

          df_mes = df_global[df_global["Mes"] == mes_nombre][
              ["Fecha", "Horas"]
          ].reset_index(drop=True)

          df_editado = st.data_editor(
              df_mes,
              key=f"editor_{i}_{mes_nombre}",
              use_container_width=True,
              hide_index=True,
              height=400,
          )

          if not df_editado.equals(df_mes):
            df_global.loc[df_global["Mes"] == mes_nombre, "Horas"] = df_editado[
                "Horas"
            ].values
            df_para_guardar = df_global[["Fecha", "Horas"]]

            if sincronizar_dataframe_a_sheet(df_para_guardar):
              registros_actuales = obtener_datos_hoja()
              tot_hoy_edit, tot_sem_edit, tot_mes_edit, _, _ = (
                  calcular_totales(registros_actuales)
              )
              st.success(
                  "🔄 ¡Cambios sincronizados con éxito en Google Drive!\n\n"
                  f"- **Total Hoy:** {formatear_horas(tot_hoy_edit)}\n"
                  f"- **Total Esta Semana:** {formatear_horas(tot_sem_edit)}\n"
                  f"- **Total Este Mes:** {formatear_horas(tot_mes_edit)}"
              )
  else:
    st.info("Aún no hay registros en la base de datos.")
