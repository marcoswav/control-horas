from datetime import datetime, timedelta
import gspread
import streamlit as st

# ------------------ CONEXIÓN CON GOOGLE SHEETS ------------------
credenciales_dict = dict(st.secrets["gcp_service_account"])
gc = gspread.service_account_from_dict(credenciales_dict)

# Abre la hoja por su enlace web real
sh = gc.open_by_url(
    "https://docs.google.com/spreadsheets/d/1FuKT6RSIbmgQlr7LdSiYBHkuMguhfN4Yd_8OPsdCt6E/edit?gid=0#gid=0"
)
worksheet = sh.get_worksheet(0)


# ------------------ FUNCIONES LÓGICAS Y DE CÁLCULO ------------------
def obtener_datos_hoja():
  """Lee la hoja y devuelve un diccionario { 'DD-MM-YYYY': total_horas } sumando duplicados."""
  try:
    registros = worksheet.get_all_records()
  except Exception:
    return {}

  diccionario_registros = {}
  for fila in registros:
    fecha = str(fila.get("Fecha", "")).strip()
    if not fecha:
      continue

    raw_horas = fila.get("Horas", 0)
    try:
      horas = float(raw_horas) if str(raw_horas).strip() != "" else 0.0
    except ValueError:
      horas = 0.0

    # Si la fecha ya estaba registrada, sumamos las horas (ej: turno partido)
    if fecha in diccionario_registros:
      diccionario_registros[fecha] += horas
    else:
      diccionario_registros[fecha] = horas

  return diccionario_registros


def formatear_horas(total_decimales):
  """Convierte un número decimal de horas en formato legible: X horas e Y minutos."""
  horas_enteras = int(total_decimales)
  minutos_restantes = round((total_decimales - horas_enteras) * 60)
  return f"{horas_enteras} horas y {minutos_restantes} minutos"


def calcular_totales(diccionario_registros):
  """Calcula el total histórico, de la semana actual y del mes actual."""
  hoy = datetime.now()
  mes_actual_str = hoy.strftime("%m-%Y")  # Formato MM-YYYY para comparar el mes

  total_historico = 0.0
  total_mes = 0.0
  total_semana = 0.0

  # Inicio y fin de la semana actual (lunes a domingo)
  inicio_semana = hoy - timedelta(days=hoy.weekday())
  inicio_semana = inicio_semana.replace(
      hour=0, minute=0, second=0, microsecond=0
  )
  fin_semana = inicio_semana + timedelta(days=6, hours=23, minutes=59)

  for fecha_str, horas in diccionario_registros.items():
    total_historico += horas

    try:
      # Parsear la fecha del registro (DD-MM-YYYY)
      fecha_dt = datetime.strptime(fecha_str, "%d-%m-%Y")

      # Comprobar si es del mes actual
      if fecha_dt.strftime("%m-%Y") == mes_actual_str:
        total_mes += horas

      # Comprobar si está dentro de la semana actual
      if inicio_semana <= fecha_dt <= fin_semana:
        total_semana += horas
    except ValueError:
      # Si hay alguna fecha mal escrita en la hoja, la ignoramos para los cálculos de tiempo
      pass

  return total_historico, total_semana, total_mes


# ------------------ INTERFAZ WEB (STREAMLIT) ------------------

st.title("🕒 Gestor de Horas de Trabajo")
hoy_str = datetime.now().strftime("%d-%m-%Y")

# Cargamos los datos actuales de la hoja
registros_actuales = obtener_datos_hoja()
tot_hist, tot_sem, tot_mes = calcular_totales(registros_actuales)

# --- APARTADOS DE RESUMEN (Métricas visuales) ---
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
  horas_decimales = round(input_horas + (input_minutos / 60), 2)
  fec = input_fecha.strip()

  try:
    # Leemos la lista de fechas actual de la columna A
    lista_fechas = worksheet.col_values(1)
  except Exception:
    lista_fechas = []

  # LÓGICA DE ACUMULACIÓN:
  # Si el día ya existe en la hoja, sumamos las nuevas horas a lo que ya tenía esa celda exacta
  if fec in lista_fechas[1:]:
    fila_idx = lista_fechas[1:].index(fec) + 2

    # Leemos lo que había guardado hasta ahora en esa fila (Columna B)
    try:
      valor_actual_celda = float(worksheet.cell(fila_idx, 2).value or 0)
    except ValueError:
      valor_actual_celda = 0.0

    nuevo_total_dia = round(valor_actual_celda + horas_decimales, 2)

    # Actualizamos la celda con la suma acumulada del día
    worksheet.update_cell(fila_idx, 2, nuevo_total_dia)
    st.success(
        f"¡Horas sumadas! El día {fec} acumula ahora un total de"
        f" {nuevo_total_dia} horas."
    )
  else:
    # Si la fecha no existe, creamos una fila nueva al final
    worksheet.append_row([fec, horas_decimales])
    st.success(f"¡Guardado nuevo registro! El día {fec} tiene {horas_decimales} horas.")

  st.rerun()
