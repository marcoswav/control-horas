from datetime import datetime, timedelta
import gspread
import pandas as pd
import streamlit as st

# ------------------ CONEXIÓN CON GOOGLE SHEETS ------------------
credenciales_dict = dict(st.secrets["gcp_service_account"])
gc = gspread.service_account_from_dict(credenciales_dict)

# Conexión buscando el archivo por su nombre exacto en Drive
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


def calcular_totales(diccionario_registros):
  hoy = datetime.now()
  hoy_str = hoy.strftime("%d-%m-%Y")
  mes_actual_str = hoy.strftime("%m-%Y")

  total_hoy = diccionario_registros.get(hoy_str, 0.0)
  total_mes = 0.0
  total_semana = 0.0

  inicio_semana = hoy - timedelta(days=hoy.weekday())
  inicio_semana = inicio_semana.replace(
      hour=0, minute=0, second=0, microsecond=0
  )
  fin_semana = inicio_semana + timedelta(days=6, hours=23, minutes=59)

  for fecha_str, horas in diccionario_registros.items():
    try:
      fecha_dt = datetime.strptime(fecha_str, "%d-%m-%Y")
      if fecha_dt.strftime("%m-%Y") == mes_actual_str:
        total_mes += horas
      if inicio_semana <= fecha_dt <= fin_semana:
        total_semana += horas
    except ValueError:
      pass

  return (
      round(total_hoy, 2),
      round(total_semana, 2),
      round(total_mes, 2),
  )


def sincronizar_dataframe_a_sheet(df_completo):
  """Vuelca los datos del DataFrame editado de vuelta a Google Sheets."""
  try:
    lote = [["Fecha", "Horas"]]
    for _, row in df_completo.iterrows():
      lote.append([str(row["Fecha"]), float(row["Horas"])])

    worksheet.clear()
    worksheet.update(lote)
  except Exception as e:
    st.error(f"Error al sincronizar con Google Drive: {e}")


# ------------------ INTERFAZ WEB (STREAMLIT) ------------------

st.title("🕒 Gestor de Horas de Trabajo")
hoy_str = datetime.now().strftime("%d-%m-%Y")

registros_actuales = obtener_datos_hoja()
tot_hoy, tot_sem, tot_mes = calcular_totales(registros_actuales)

# --- RESUMEN SUPERIOR ---
st.markdown("### 📊 Resumen Actual")
col1, col2, col3 = st.columns(3)
with col1:
  st.metric("Hoy", f"{tot_hoy} h")
with col2:
  st.metric("Esta Semana", f"{tot_sem} h")
with col3:
  st.metric("Este Mes", f"{tot_mes} h")

st.markdown("---")

# --- REGISTRAR NUEVAS HORAS ---
st.subheader("Registrar Horas")
input_fecha = st.text_input("Fecha (DD-MM-YYYY):", value=hoy_str)
input_horas = st.number_input("Horas enteras:", min_value=0, value=8, step=1)
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
  tot_hoy_nuevo, tot_sem_nuevo, tot_mes_nuevo = calcular_totales(
      registros_actuales
  )

  st.success(
      f"✅ ¡Guardado con éxito!\n\n"
      f"- **Total Hoy:** {tot_hoy_nuevo} h\n"
      f"- **Total Esta Semana:** {tot_sem_nuevo} h\n"
      f"- **Total Este Mes:** {tot_mes_nuevo} h"
  )

st.markdown("---")

# --- TABLA EDITABLE Y AGRUPADA POR MES ---
st.subheader("📋 Historial y Edición por Meses")

if registros_actuales:
  lista_datos = [
      {"Fecha": f, "Horas": h} for f, h in registros_actuales.items()
  ]
  df_global = pd.DataFrame(lista_datos)

  df_global["Fecha_dt"] = pd.to_datetime(
      df_global["Fecha"], format="%d-%m-%Y", errors="coerce"
  )
  df_global = df_global.sort_values(by="Fecha_dt", ascending=False)

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
  df_global["Mes"] = df_global["Fecha_dt"].apply(
      lambda x: (
          f"{meses_espanol[x.month]} {x.year}"
          if pd.notnull(x)
          else "Desconocido"
      )
  )
  df_global = df_global.drop(columns=["Fecha_dt"])

  meses_disponibles = [str(m) for m in df_global["Mes"].unique().tolist()]

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
        )

        if not df_editado.equals(df_mes):
          df_global.loc[df_global["Mes"] == mes_nombre, "Horas"] = df_editado[
              "Horas"
          ].values
          df_para_guardar = df_global[["Fecha", "Horas"]]

          sincronizar_dataframe_a_sheet(df_para_guardar)
          st.success(
              "🔄 ¡Cambios guardados y sincronizados con Google Drive en"
              " directo!"
          )
          st.rerun()
else:
  st.info("Aún no hay registros en la base de datos.")
