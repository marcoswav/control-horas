from datetime import datetime, timedelta
import gspread
import streamlit as st

# ------------------ CONEXIÓN CON GOOGLE SHEETS ------------------
credenciales_dict = dict(st.secrets["gcp_service_account"])
gc = gspread.service_account_from_dict(credenciales_dict)

sh = gc.open_by_url(
    "https://docs.google.com/spreadsheets/d/1FuKT6RSIbmgQlr7LdSiYBHkuMguhfN4Yd_8OPsdCt6E/edit?gid=0#gid=0"
)
worksheet = sh.get_worksheet(0)


# ------------------ FUNCIONES LÓGICAS Y DE CÁLCULO ------------------
def limpiar_fecha(fec_str):
  """Estandariza la fecha a formato DD-MM-YYYY para evitar desajustes."""
  fec_str = str(fec_str).strip()
  try:
    # Intenta parsear y devolver en formato limpio DD-MM-YYYY
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
  """Convierte decimales a horas y minutos exactos sin errores de desborde."""
  if total_decimales < 0:
    total_decimales = 0.0
  horas_enteras = int(total_decimales)
  minutos_restantes = int(round((total_decimales - horas_enteras) * 60))

  if minutos_restantes == 60:
    horas_enteras += 1
    minutos_restantes = 0

  return f"{horas_enteras} horas y {minutos_restantes} minutos"


def calcular_totales(diccionario_registros):
  hoy = datetime.now()
  mes_actual_str = hoy.strftime("%m-%Y")

  total_historico = 0.0
  total_mes = 0.0
  total_semana = 0.0

  inicio_semana = hoy - timedelta(days=hoy.weekday())
  inicio_semana = inicio_semana.replace(
      hour=0, minute=0, second=0, microsecond=0
  )
  fin_semana = inicio_semana + timedelta(days=6, hours=23, minutes=59)

  for fecha_str, horas in diccionario_registros.items():
    total_historico += horas
    try:
      fecha_dt = datetime.strptime(fecha_str, "%d-%m-%Y")
      if fecha_dt.strftime("%m-%Y") == mes_actual_str:
        total_mes += horas
      if inicio_semana <= fecha_dt <= fin_semana:
        total_semana += horas
    except ValueError:
      pass

  return total_historico, total_semana, total_mes


# ------------------ INTERFAZ WEB (STREAMLIT) ------------------

st.title("🕒 Gestor de Horas de Trabajo")
hoy_str = datetime.now().strftime("%d-%m-%Y")

# Cargamos datos frescos de la hoja
registros_actuales = obtener_datos_hoja()
tot_hist, tot_sem, tot_mes = calcular_totales(registros_actuales)

# --- MÉTRICAS SUPERIORES ---
col1, col2, col3 = st.columns(3)
with col1:
  st.metric("Esta Semana", formatear_horas(tot_sem))
with col2:
  st.metric("Este Mes", formatear_horas(tot_mes))
with col3:
  st.metric("Histórico Total", formatear_horas(tot_hist))

st.markdown("---")

# --- CONTROLES DE ENTRADA ---
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
    # Leemos la columna entera de fechas de la hoja
    columna_fechas_raw = worksheet.col_values(1)
  except Exception:
    columna_fechas_raw = []

  # Buscamos si la fecha ya existe en la hoja (ignorando cabecera en índice 0)
  encontrado = False
  fila_encontrada = -1

  for idx, val in enumerate(columna_fechas_raw[1:], start=2):
    if limpiar_fecha(val) == fec:
      encontrado = True
      fila_encontrada = idx
      break

  if encontrado:
    # Si existe, leemos el valor actual de la columna B en esa misma fila
    try:
      valor_previo = float(worksheet.cell(fila_encontrada, 2).value or 0)
    except ValueError:
      valor_previo = 0.0

    nuevo_total_dia = round(valor_previo + horas_nuevas, 2)
    # Actualizamos la celda con la suma acumulada
    worksheet.update_cell(fila_encontrada, 2, nuevo_total_dia)

    # Mensaje detallado sin refrescar la página bruscamente
    st.success(
        f"✅ ¡Actualizado con éxito! El día {fec} sumaba {valor_previo}"
        f" horas, se han añadido {horas_nuevas} horas y ahora acumula un"
        f" **total de {nuevo_total_dia} horas** ({formatear_horas(nuevo_total_dia)})."
    )
  else:
    # Si no existe, creamos una fila nueva al final
    worksheet.append_row([fec, horas_nuevas])
    st.success(
        f"🎉 ¡Guardado nuevo registro! El día {fec} se ha registrado con"
        f" **{horas_nuevas} horas** ({formatear_horas(horas_nuevas)})."
    )
