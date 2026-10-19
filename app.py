"""Control de horas: Streamlit + Google Sheets. Una hoja visible."""
from __future__ import annotations

import calendar
import json
import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import gspread
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Control horas work", page_icon="https://cdn-icons-png.flaticon.com/512/194/194978.png", layout="wide")
st.markdown('''<style>
html,body,[class*="css"]{font-size:18px!important}
[data-testid="stMetricValue"]{font-size:1.8rem!important}
[data-testid="stMetricLabel"]{font-size:1.1rem!important}
div[data-testid="stProgress"]>div>div>div{background-image:linear-gradient(90deg,#3b82f6,#1d4ed8,#60a5fa);background-size:200% 100%;animation:gradientAnimation 1.5s ease infinite;transition:width .6s ease-in-out}
div[data-testid="stProgress"]:has([role="progressbar"][aria-valuenow="100"])>div>div>div,
div[data-testid="stProgress"]:has([role="progressbar"][aria-valuenow="100.0"])>div>div>div{background-image:linear-gradient(90deg,#ec4899,#be185d,#f472b6)!important}
@keyframes gradientAnimation{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
</style>''', unsafe_allow_html=True)

TZ = ZoneInfo("Europe/Madrid")
START = date(2026, 7, 22)
DAILY_SECONDS = 4 * 3600 + 36 * 60
HEADERS = ["Fecha", "Horas trabajadas", "Laborable", "Objetivo", "Balance diario", "Motivo / observaciones", "Balance (min)"]
MONTHS = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def now():
    return datetime.now(TZ)


def date_parse(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip().replace("'", "")
    # Google Sheets/Excel serial dates: 1899-12-30 is serial day zero.
    # When Sheets converts a USER_ENTERED date, FORMATTED_VALUE may return
    # the serial as a string if the cell's format is later changed to TEXT.
    if re.fullmatch(r"\d+(?:\.0+)?", s):
        serial = int(float(s))
        if 20000 <= serial <= 100000:
            try:
                return date(1899, 12, 30) + timedelta(days=serial)
            except OverflowError:
                return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def seconds_parse(value, sheet_duration=True):
    """Sheets formatted duration, legacy decimal hours, or timedelta."""
    if isinstance(value, timedelta):
        return max(0, round(value.total_seconds()))
    if isinstance(value, (float, int)):
        return max(0, round(float(value) * (86400 if sheet_duration else 3600)))
    s = str(value or "").strip().lower().replace("'", "")
    if not s:
        return 0
    match = re.fullmatch(r"(\d+):(\d{1,2})(?::(\d{1,2}))?", s)
    if match:
        h, m, sec = match.groups()
        return int(h)*3600 + int(m)*60 + int(sec or 0)
    match = re.fullmatch(r"(\d+)\s*h(?:\s*y?\s*(\d+)\s*min)?", s)
    if match:
        return int(match.group(1))*3600 + int(match.group(2) or 0)*60
    try:
        return max(0, round(float(s.replace(",", ".")) * (86400 if sheet_duration else 3600)))
    except ValueError:
        raise ValueError(f"Duración no reconocida: {value!r}")


def fmt(seconds):
    sign = "−" if seconds < 0 else ""
    minutes = round(abs(seconds) / 60)
    return f"{sign}{minutes//60} h {minutes%60:02d} min"


def fmt_editable_duration(seconds):
    """Duracion editable en el historial: horas:minutos."""
    minutes = round(max(0, seconds) / 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def parse_editable_duration(value):
    """Acepta H:MM, HH:MM o H:MM:SS; no interpreta decimales ambiguos."""
    if not isinstance(value, str):
        raise ValueError("Escribe la duracion como H:MM, por ejemplo 5:30.")
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?\s*", value)
    if not match:
        raise ValueError("Formato incorrecto. Usa H:MM (por ejemplo 5:30).")
    h, m, sec = (int(part or 0) for part in match.groups())
    if h > 24 or m > 59 or sec > 59 or (h == 24 and (m or sec)):
        raise ValueError("La duracion debe estar entre 0:00 y 24:00.")
    return h * 3600 + m * 60 + sec


def fmt_clock(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds//3600} h : {(seconds%3600)//60:02d} min : {seconds%60:02d} seg"


def holiday_name(day):
    """ES/Andalucía via holidays; Granada capital local holidays confirmed for 2026."""
    if day.year == 2026 and day in (date(2026, 1, 2), date(2026, 6, 4)):
        return {date(2026, 1, 2): "Fiesta local de Granada", date(2026, 6, 4): "Corpus Christi (Granada)"}[day]
    try:
        import holidays
        es = holidays.country_holidays("ES", subdiv="AN", years=[day.year], observed=True)
        return str(es.get(day) or "")
    except Exception:
        return ""


def default_workday(day):
    if day < START:
        return False, "Anterior al inicio"
    if day.weekday() >= 5:
        return False, "Fin de semana"
    name = holiday_name(day)
    return (False, name) if name else (True, "")


@st.cache_resource
def worksheet():
    creds = dict(st.secrets["gcp_service_account"])
    client = gspread.service_account_from_dict(creds)
    spreadsheet_id = st.secrets.get("spreadsheet_id", "1FuKT6RSIbmgQlr7LdSiYBHkuMguhfN4Yd_8OPsdCt6E")
    sh = client.open_by_key(spreadsheet_id)
    try:
        return sh.worksheet("Registro de horas")
    except gspread.WorksheetNotFound:
        return sh.get_worksheet(0)


def read_records(ws):
    rows = ws.get_all_values()
    if not rows:
        raise ValueError("La hoja está vacía. Restaura primero la copia de seguridad.")
    if rows[0][0].strip().lower() != "fecha":
        raise ValueError("La columna A debe tener la cabecera 'Fecha'.")
    records, invalid = {}, []
    is_duration_sheet = len(rows[0]) > 1 and "trabajadas" in rows[0][1].lower()
    for idx, row in enumerate(rows[1:], start=2):
        if not row or not row[0].strip():
            continue
        d = date_parse(row[0])
        if d is None:
            invalid.append(f"Fila {idx}: fecha {row[0]!r}")
            continue
        try:
            seconds = seconds_parse(row[1] if len(row)>1 else "", sheet_duration=is_duration_sheet)
        except ValueError as e:
            invalid.append(f"Fila {idx}: {e}")
            continue
        if seconds > 24 * 3600:
            invalid.append(f"Fila {idx}: duración de {fmt(seconds)}; revisa el formato de la columna B")
            continue
        flag = (row[2].strip().lower() if len(row)>2 else "")
        default, reason = default_workday(d)
        if flag in ("sí", "si", "yes", "true", "1"):
            work = True
        elif flag in ("no", "false", "0"):
            work = False
        else:
            work = default
        note = row[5].strip() if len(row)>5 else ""
        # El motivo anterior al inicio no puede corresponder a octubre de 2026.
        if d >= START and note.lower().startswith("anterior al inicio"):
            note = reason
        if d in records:
            records[d]["seconds"] += seconds
            invalid.append(f"Fecha duplicada {d:%d/%m/%Y}: horas sumadas; revisar hoja")
        else:
            records[d] = {"seconds": seconds, "work": work, "note": note or reason}
    return records, invalid


def sheet_row(day, record, index):
    work = record["work"]
    # Sheets duration numeric serial (days), NOT decimal hours.
    return [(day - date(1899, 12, 30)).days, record["seconds"] / 86400, "Sí" if work else "No",
            f'=IF(C{index}="Sí",TIME(4,36,0),0)',
            f'=IF(G{index}<0,"-","+")&TEXT(ABS(G{index})/1440,"[h]:mm")',
            record.get("note", ""), f"=ROUND((B{index}-D{index})*1440,0)"]


def ensure_sheet(ws, records, warnings):
    """Append missing days; trim trailing future rows, never clear the whole sheet."""
    today = now().date()
    if warnings:
        # Never rewrite uncertain/duplicated source data.
        return False
    future = [d for d in records if d > today]
    missing = [START + timedelta(days=i) for i in range((today-START).days+1) if START+timedelta(days=i) not in records] if today>=START else []
    # One-time canonical rewrite only when required: backup strongly recommended.
    # Update first, delete only after successful update. Keeps all pre-start history.
    if not missing and not future:
        return False
    for d in missing:
        work, reason = default_workday(d)
        records[d] = {"seconds": 0, "work": work, "note": reason}
    kept = sorted(d for d in records if d <= today)
    data = [HEADERS] + [sheet_row(d, records[d], i) for i,d in enumerate(kept, start=2)]
    ws.update(range_name=f"A1:G{len(data)}", values=data, value_input_option="USER_ENTERED")
    existing_count = len(ws.get_all_values())
    if existing_count > len(data):
        ws.delete_rows(len(data)+1, existing_count)
    format_columns(ws, len(data))
    for d in future:
        records.pop(d, None)
    return True


def format_columns(ws, last_row):
    """Uniformar toda la tabla, con desplegables, colores y formatos en Sheets."""
    if last_row < 2:
        return
    sheet_id = ws.id
    # Usar batch_update para aplicar formato y validaciones de una sola vez.
    requests = []
    def repeat(start_row, end_row, start_col, end_col, fmt, fields="userEnteredFormat"):
        requests.append({"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": start_row,
                      "endRowIndex": end_row, "startColumnIndex": start_col,
                      "endColumnIndex": end_col},
            "cell": {"userEnteredFormat": fmt},
            "fields": fields}})

    repeat(0, 1, 0, 7, {"backgroundColor": {"red": 0.10, "green": 0.16, "blue": 0.28},
                         "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}})
    # El formato de la fecha se mantiene como fecha real (número de serie de Sheets).
    base = {"backgroundColor": {"red": 1, "green": 1, "blue": 1},
            "verticalAlignment": "MIDDLE"}
    repeat(1, last_row, 0, 7, base)
    for row in range(2, last_row, 2):
        repeat(row, min(row+1, last_row), 0, 7,
               {"backgroundColor": {"red": .94, "green": .96, "blue": .99},
                "verticalAlignment": "MIDDLE"})
    # Formatos por columna, después de los fondos.
    repeat(1, last_row, 0, 1, {"numberFormat": {"type": "DATE", "pattern": "dd/mm/yyyy"}}, "userEnteredFormat.numberFormat")
    for col in (1, 3):
        repeat(1, last_row, col, col+1,
               {"numberFormat": {"type": "TIME", "pattern": "[h]:mm:ss"}}, "userEnteredFormat.numberFormat")
    requests.append({"setDataValidation": {
        "range": {"sheetId": sheet_id, "startRowIndex": 1,
                  "endRowIndex": ws.row_count, "startColumnIndex": 2, "endColumnIndex": 3},
        "rule": {"condition": {"type": "ONE_OF_LIST", "values": [
            {"userEnteredValue": "Sí"}, {"userEnteredValue": "No"}]},
            "strict": True, "showCustomUi": True}}})
    requests.append({"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 6, "endIndex": 7},
        "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}})
    ws.spreadsheet.batch_update({"requests": requests})


def repair_sheet(ws, records):
    """Reescribir solo la tabla conocida tras lectura validada; no toca I:J."""
    ordered = sorted(d for d in records if d <= now().date())
    if not ordered:
        return
    values = [HEADERS] + [sheet_row(d, records[d], idx)
                          for idx, d in enumerate(ordered, start=2)]
    ws.update(range_name=f"A1:G{len(values)}", values=values,
              value_input_option="USER_ENTERED")
    format_columns(ws, len(values))


def save_day(ws, records, day, seconds=None, work=None, note=None):
    if day > now().date():
        raise ValueError("No se pueden editar fechas futuras")
    record = dict(records.get(day, {}))
    if not record:
        default, reason = default_workday(day)
        record = {"seconds": 0, "work": default, "note": reason}
    if seconds is not None:
        record["seconds"] = int(seconds)
    if work is not None:
        record["work"] = bool(work)
        record["note"] = "Cambio manual" if note is None else note
    if note is not None:
        record["note"] = note
    ordered = sorted(records)
    if day in records:
        row_index = ordered.index(day)+2
        ws.update(range_name=f"A{row_index}:G{row_index}", values=[sheet_row(day,record,row_index)], value_input_option="USER_ENTERED")
    else:
        row_index = len(ordered)+2
        ws.update(range_name=f"A{row_index}:G{row_index}", values=[sheet_row(day,record,row_index)], value_input_option="USER_ENTERED")
        format_columns(ws, row_index)
    records[day] = record


def timer_read(ws):
    """Private timer state in I:J on the SAME worksheet (single-user app)."""
    cells = ws.get("I1:J4")
    vals = {r[0]: r[1] for r in cells if len(r)>1}
    try:
        accumulated = max(0,int(vals.get("Acumulado segundos", "0")))
        running = vals.get("Activo", "No") == "Sí"
        started = datetime.fromisoformat(vals["Inicio ISO"]) if running else None
        if started and started.tzinfo is None:
            started = started.replace(tzinfo=TZ)
        return accumulated, running, started
    except (ValueError, KeyError):
        return 0, False, None


def timer_write(ws, accumulated, running, started):
    ws.update(range_name="I1:J4", values=[
        ["Estado cronómetro", "Persistente"],
        ["Acumulado segundos", str(int(accumulated))],
        ["Activo", "Sí" if running else "No"],
        ["Inicio ISO", started.isoformat() if started else ""]], value_input_option="RAW")


def timer_seconds(state):
    accum, running, started = state
    return accum + (max(0,int((now()-started).total_seconds())) if running and started else 0)


def plot_ring(actual, target):
    fig, ax = plt.subplots(figsize=(2.2,2.2))
    fig.patch.set_facecolor("none")
    ax.set_facecolor("none")
    if target <= 0:
        vals, colors = ([1], ["#ec4899"])
    elif actual >= target:
        vals, colors = ([target, max(0,actual-target)], ["#334155", "#ec4899"])
        if vals[1] == 0:
            vals = [1]
            colors = ["#ec4899"]
    else:
        vals, colors = ([max(0,actual),target-max(0,actual)], ["#334155", "#3b82f6"])
    ax.pie(vals, colors=colors, startangle=90, wedgeprops={"width":.4,"edgecolor":"none"})
    ax.set(aspect="equal")
    plt.tight_layout()
    return fig


def date_range(a,b):
    if a>b:
        return []
    return [a+timedelta(days=i) for i in range((b-a).days+1)]


def total(records, a, b, field="seconds"):
    return sum(records[d][field] if field=="seconds" else (DAILY_SECONDS if records[d]["work"] else 0)
               for d in date_range(a,b) if d in records)


def refresh():
    st.rerun()

st.title("Control horas work")
st.caption("Granada capital · Desde el 22/07/2026 · 23 h/semana · 4 h 36 min por día laborable")
try:
    ws = worksheet()
    records, warnings = read_records(ws)
    if warnings:
        st.error("Se detectaron registros que necesitan revisión. Por seguridad se ha desactivado la sincronización y la edición.")
        for warning in warnings[:12]:
            st.warning(warning)
        st.stop()
    updated = ensure_sheet(ws, records, warnings)
    if updated:
        st.toast("Calendario actualizado hasta hoy")
    state = timer_read(ws)
except Exception as exc:
    st.error(f"No se pudo cargar Google Sheets: {exc}")
    st.info("Comprueba el ID de la hoja, las credenciales y los permisos de la cuenta de servicio. No se han modificado tus datos.")
    st.stop()

st.divider()
today = now().date()
yesterday = today-timedelta(days=1)
week_start = today-timedelta(days=today.weekday())
month_start = today.replace(day=1)
worked_today = total(records,today,today)
worked_week = total(records,week_start,today)
worked_month = total(records,month_start,today)
expected_today = total(records,today,today,"target")
expected_week = total(records,week_start,today,"target")
expected_month = total(records,month_start,today,"target")
worked_hist = sum(r["seconds"] for d,r in records.items() if d <= yesterday)
expected_hist = total(records,START,yesterday,"target")
worked_provisional = sum(r["seconds"] for d,r in records.items() if d <= today)
expected_provisional = total(records,START,today,"target")

left,right = st.columns([1.1,.9])
with left:
    st.markdown("### Cronómetro y Registro de Horas")
    with st.container(border=True):
        elapsed = timer_seconds(state)
        st.markdown(f"### ⏱️ {fmt_clock(elapsed)}")
        a,b,c = st.columns(3)
        with a:
            if not state[1] and st.button("Activar", type="primary", use_container_width=True):
                timer_write(ws,state[0],True,now());refresh()
            if state[1] and st.button("Pausar",use_container_width=True):
                timer_write(ws,elapsed,False,None);refresh()
        with b:
            if st.button("Resetear",use_container_width=True):
                timer_write(ws,0,False,None);refresh()
        with c:
            if st.button("Registrar crono",use_container_width=True):
                if state[1]:
                    st.warning("Pausa primero el cronómetro antes de registrarlo.")
                elif elapsed<1:
                    st.warning("No hay tiempo para registrar.")
                else:
                    try:
                        save_day(ws,records,today,seconds=worked_today+elapsed)
                        timer_write(ws,0,False,None)
                        st.success("Tiempo registrado")
                        refresh()
                    except Exception as exc:
                        st.error(f"No se pudo completar el registro: {exc}. Comprueba la hoja antes de reintentar.")
        st.divider()
        st.write("**O ingresar horas manualmente:**")
        with st.form("manual",clear_on_submit=False):
            x,y,z = st.columns(3)
            with x: selected_day = st.date_input("Fecha",today,max_value=today)
            with y: hours = st.number_input("Horas",min_value=0,max_value=1000,value=0,step=1)
            with z: minutes = st.number_input("Minutos",min_value=0,max_value=59,value=0,step=1)
            submitted = st.form_submit_button("Registrar",use_container_width=True)
        if submitted:
            seconds = int(hours)*3600+int(minutes)*60
            if seconds<=0:
                st.warning("Introduce una duración positiva")
            else:
                try:
                    save_day(ws,records,selected_day,seconds=records.get(selected_day,{}).get("seconds",0)+seconds)
                    st.success("Horas guardadas")
                    refresh()
                except Exception as exc:
                    st.error(f"Error al guardar: {exc}")

    st.divider()
    st.markdown("### Resumen actual")
    cols = st.columns(3)
    for col,label,actual,target,caption in zip(cols,["Hoy","Semana","Mes"],
            [worked_today,worked_week,worked_month],[expected_today,expected_week,expected_month],
            [today.strftime("%d/%m/%Y"),f"Desde {week_start:%d/%m}",f"Desde {month_start:%d/%m}"]):
        with col:
            pct = 1.0 if target==0 else min(1.0,actual/target)
            st.progress(pct,text=f"Objetivo: {int(pct*100)} %")
            with st.container(border=True):
                st.metric(label,fmt(actual))
                st.caption(f"{caption} · Meta: {fmt(target)}")
            fig=plot_ring(actual,target)
            st.pyplot(fig,use_container_width=True)
            plt.close(fig)
    st.caption("Los objetivos semanales y mensuales se calculan hasta hoy; los días no laborables tienen meta 0 y aparecen completados.")

with right:
    st.markdown("### Balance de horas")
    debt = expected_hist - worked_hist
    progress = 1.0 if expected_hist <= 0 else min(1.0, worked_hist / expected_hist)
    st.progress(progress, text="Cumplimiento de horas obligatorias hasta ayer (incluido crédito anterior)")
    with st.container(border=True):
        st.metric("Balance de horas (positivo: pendientes · negativo: a favor)", fmt(debt))
        st.caption("Un valor positivo indica horas pendientes; uno negativo indica horas a favor. Se incluyen las horas anteriores al 22/07.")
    # Diagnóstico opcional, sin segundo saldo en la tarjeta de deuda.
    with st.expander("Comprobar cómo se calcula la deuda"):
        st.write(f"Obligatorias hasta ayer: **{fmt(expected_hist)}**")
        st.write(f"Trabajadas hasta ayer, incluidas las anteriores al inicio: **{fmt(worked_hist)}**")
        st.write(f"Horas a favor anteriores al 22/07/2026: **{fmt(total(records, min(records) if records else START, START - timedelta(days=1)))}**")
        st.write("Deuda = obligatorias desde el 22/07 − todas las horas registradas hasta ayer. Las horas anteriores al 22/07 reducen la deuda.")
        months=sorted({(d.year,d.month) for d in records if START<=d<=yesterday})
        for year,month in months:
            a=max(START,date(year,month,1))
            b=min(yesterday,date(year,month,calendar.monthrange(year,month)[1]))
            m_expected=total(records,a,b,"target")
            m_worked=total(records,a,b)
            st.write(f"{MONTHS[month].capitalize()} {year}: objetivo {fmt(m_expected)}, trabajadas {fmt(m_worked)}")

    st.divider()
    st.subheader("Horas trabajadas anteriormente")
    st.caption("Puedes cambiar el estado laborable de cualquier fecha y editar su duración. Las fechas futuras no se muestran.")
    months=sorted({(d.year,d.month) for d in records if d<=today},reverse=True)
    if not months:
        st.info("No hay registros todavía")
    else:
        options=[f"{MONTHS[m].capitalize()} {y}" for y,m in months]
        choice=st.selectbox("Mes del historial",range(len(months)),format_func=lambda i:options[i])
        year,month=months[choice]
        subset=sorted(d for d in records if d.year==year and d.month==month and d<=today)
        data=[]
        for d in subset:
            r=records[d]
            data.append({"Fecha":d.strftime("%d/%m/%Y"),"Día": ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][d.weekday()],"Laborable":r["work"],
                         "Horas":r["seconds"]//3600,"Minutos":(r["seconds"]%3600)//60,
                         "Objetivo":fmt(DAILY_SECONDS if r["work"] else 0),
                         "Trabajado":fmt_editable_duration(r["seconds"]),"Motivo":r.get("note","")})
        df=pd.DataFrame(data)
        # Column layout is a deliberate, persistent setting, not Streamlit's
        # temporary drag/hide state (which data_editor does not expose to Python).
        ALL_COLS = list(df.columns)
        layout_key = "historial_layout_v1"
        if layout_key not in st.session_state:
            try:
                stored = json.loads((ws.acell("L2").value or "{}"))
                stored_cols = stored.get("columns", ALL_COLS)
                valid_cols = [c for c in stored_cols if c in ALL_COLS]
                st.session_state[layout_key] = valid_cols if valid_cols else ALL_COLS.copy()
            except (ValueError, TypeError, AttributeError):
                st.session_state[layout_key] = ALL_COLS.copy()

        def persist_layout(cols):
            if not cols:
                st.session_state["layout_notice"] = ("error", "Debe quedar al menos una columna visible.")
                return
            try:
                ws.update(range_name="L1:L2", values=[["Preferencias historial"],
                          [json.dumps({"columns": cols}, ensure_ascii=False)]], value_input_option="RAW")
                st.session_state[layout_key] = cols
                st.session_state["layout_notice"] = ("success", "Distribución de columnas guardada en Google Sheets.")
            except Exception as exc:
                st.session_state["layout_notice"] = ("error", f"No se pudo guardar la distribución: {exc}")

        with st.expander("Personalizar columnas (se conserva al recargar)"):
            visible = st.multiselect("Columnas visibles", ALL_COLS,
                        default=st.session_state[layout_key], key="history_visible_cols")
            if visible != st.session_state[layout_key]:
                if st.button("Aplicar columnas visibles", key="apply_visible"):
                    # Retain the relative order of existing columns.
                    current = st.session_state[layout_key]
                    ordered = [c for c in current if c in visible] + [c for c in visible if c not in current]
                    persist_layout(ordered)
                    st.rerun()
            if st.session_state[layout_key]:
                move_col = st.selectbox("Columna que quieres mover", st.session_state[layout_key], key="move_col")
                up, down = st.columns(2)
                with up:
                    if st.button("⬅ Mover a la izquierda", use_container_width=True):
                        order = st.session_state[layout_key].copy()
                        idx = order.index(move_col)
                        if idx > 0:
                            order[idx-1], order[idx] = order[idx], order[idx-1]
                            persist_layout(order)
                            st.rerun()
                with down:
                    if st.button("Mover a la derecha ➡", use_container_width=True):
                        order = st.session_state[layout_key].copy()
                        idx = order.index(move_col)
                        if idx < len(order)-1:
                            order[idx+1], order[idx] = order[idx], order[idx+1]
                            persist_layout(order)
                            st.rerun()
        if "layout_notice" in st.session_state:
            level, msg = st.session_state.pop("layout_notice")
            (st.success if level == "success" else st.error)(msg)

        editor_key = f"editor_{year}_{month}"

        def autosave_history():
            """Runs on cell commit. Validate all edits before any Sheets write."""
            try:
                edited_rows = st.session_state.get(editor_key, {}).get("edited_rows", {})
                if not edited_rows:
                    return
                # Re-read to avoid overwriting changes made in another browser/tab.
                latest, issues = read_records(ws)
                if issues:
                    raise ValueError("Google Sheets contiene filas pendientes de revisión; no se ha guardado nada.")
                changes = []
                for raw_idx, patch in edited_rows.items():
                    idx = int(raw_idx)
                    if idx < 0 or idx >= len(subset):
                        raise ValueError("La fila editada ya no existe.")
                    d = subset[idx]
                    original = records[d]
                    current = latest.get(d)
                    if current is None or current != original:
                        raise ValueError(f"El día {d:%d/%m/%Y} cambió en Google Sheets. Recarga antes de editarlo.")
                    if any(c not in ("Laborable", "Horas", "Minutos", "Trabajado", "Motivo") for c in patch):
                        raise ValueError("Se intentó modificar una columna de solo lectura.")
                    if "Trabajado" in patch:
                        seconds = parse_editable_duration(patch["Trabajado"])
                    elif "Horas" not in patch and "Minutos" not in patch:
                        seconds = original["seconds"]
                    else:
                        hours = patch.get("Horas", df.iloc[idx]["Horas"])
                        minutes = patch.get("Minutos", df.iloc[idx]["Minutos"])
                        if isinstance(hours, bool) or isinstance(minutes, bool):
                            raise ValueError("Las horas y los minutos deben ser numeros enteros.")
                        try:
                            h, m = int(hours), int(minutes)
                            valid = (h == float(hours) and m == float(minutes))
                        except (TypeError, ValueError, OverflowError):
                            valid = False
                        if not valid or not (0 <= h <= 24 and 0 <= m <= 59) or h*60+m > 1440:
                            raise ValueError("La duración debe estar entre 0:00 y 24:00, con minutos entre 0 y 59.")
                        seconds = h*3600 + m*60
                    work = patch.get("Laborable", original["work"])
                    if not isinstance(work, bool):
                        raise ValueError("El valor Laborable debe ser Sí o No.")
                    note = patch.get("Motivo", original.get("note", ""))
                    if note is None:
                        note = ""
                    note = str(note)
                    if len(note) > 1000:
                        raise ValueError("El motivo no puede superar 1000 caracteres.")
                    if seconds != original["seconds"] or work != original["work"] or note != original.get("note", ""):
                        changes.append((d, seconds, work, note))
                for d, seconds, work, note in changes:
                    save_day(ws, latest, d, seconds=seconds, work=work, note=note)
                # Remove pending edits only after all writes succeeded.
                st.session_state.pop(editor_key, None)
                st.session_state["autosave_notice"] = ("success", f"{len(changes)} día(s) guardado(s) automáticamente en Google Sheets.")
            except Exception as exc:
                st.session_state["autosave_notice"] = ("error", f"No se ha podido completar el guardado: {exc}. Revisa Google Sheets antes de reintentar.")

        # The editor's own drag/reorder/hide interactions are not persistent;
        # use the settings above to keep column layout across devices/reloads.
        st.data_editor(df,hide_index=True,use_container_width=True,key=editor_key,
            column_order=st.session_state[layout_key],
            on_change=autosave_history,
            disabled=["Fecha","Día","Objetivo"],
            column_config={"Laborable":st.column_config.CheckboxColumn("Laborable"),
                           "Horas":st.column_config.NumberColumn("Horas",min_value=0,max_value=24,step=1),
                           "Minutos":st.column_config.NumberColumn("Minutos",min_value=0,max_value=59,step=1),
                           "Trabajado":st.column_config.TextColumn("Trabajado (H:MM)", help="Edita el total del día, por ejemplo 5:30. Se sustituye el total anterior y se guarda en Google Sheets."),
                           "Motivo":st.column_config.TextColumn("Motivo")})
        if "autosave_notice" in st.session_state:
            level, msg = st.session_state.pop("autosave_notice")
            (st.success if level == "success" else st.error)(msg)
        st.caption("Edita «Trabajado» con formato H:MM para corregir el total del día. También puedes editar Horas y Minutos. Los cambios se guardan al confirmar la celda. Los nuevos registros manuales y del cronómetro se SUMAN a las horas existentes. Para conservar columnas ocultas o reordenadas, usa «Personalizar columnas».")

st.divider()
st.markdown("### Herramientas de Google Sheets")
actions_a, actions_b, actions_c = st.columns(3)
with actions_a:
    if st.button("🔄 Recargar Google Sheets", use_container_width=True):
        refresh()
with actions_b:
    spreadsheet_id = st.secrets.get("spreadsheet_id", "1FuKT6RSIbmgQlr7LdSiYBHkuMguhfN4Yd_8OPsdCt6E")
    st.link_button("📊 Google Sheets", f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit", use_container_width=True)
with actions_c:
    if st.button("🛠 Reparar formato y motivos de la hoja", use_container_width=True):
        try:
            repair_sheet(ws, records)
            st.success("Formato y motivos corregidos. Recargando...")
            refresh()
        except Exception as exc:
            st.error(f"No se pudo reparar la hoja: {exc}")

if state[1]:
    time.sleep(1)
    st.rerun()
