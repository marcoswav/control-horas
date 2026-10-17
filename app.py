"""Control de horas: Streamlit + Google Sheets. Una hoja visible."""
from __future__ import annotations

import calendar
import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import gspread
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Control horas work", page_icon="⏱️", layout="wide")
st.markdown('''<style>
html,body,[class*="css"]{font-size:18px!important}
[data-testid="stMetricValue"]{font-size:1.8rem!important}
[data-testid="stMetricLabel"]{font-size:1.1rem!important}
div[data-testid="stProgress"]>div>div>div{background-image:linear-gradient(90deg,#3b82f6,#1d4ed8,#60a5fa);background-size:200% 100%;animation:gradientAnimation 1.5s ease infinite;transition:width .6s ease-in-out}
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


def seconds_parse(value):
    """Sheets formatted duration, legacy decimal hours, or timedelta."""
    if isinstance(value, timedelta):
        return max(0, round(value.total_seconds()))
    if isinstance(value, (float, int)):
        return max(0, round(float(value) * 3600))
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
        return max(0, round(float(s.replace(",", "."))*3600))
    except ValueError:
        raise ValueError(f"Duración no reconocida: {value!r}")


def fmt(seconds):
    sign = "−" if seconds < 0 else ""
    minutes = round(abs(seconds) / 60)
    return f"{sign}{minutes//60} h {minutes%60:02d} min"


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
    for idx, row in enumerate(rows[1:], start=2):
        if not row or not row[0].strip():
            continue
        d = date_parse(row[0])
        if d is None:
            invalid.append(f"Fila {idx}: fecha {row[0]!r}")
            continue
        try:
            seconds = seconds_parse(row[1] if len(row)>1 else "")
        except ValueError as e:
            invalid.append(f"Fila {idx}: {e}")
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
        if d in records:
            records[d]["seconds"] += seconds
            invalid.append(f"Fecha duplicada {d:%d/%m/%Y}: horas sumadas; revisar hoja")
        else:
            records[d] = {"seconds": seconds, "work": work, "note": note or reason}
    return records, invalid


def sheet_row(day, record, index):
    work = record["work"]
    # Sheets duration numeric serial (days), NOT decimal hours.
    return ["'" + day.strftime("%d/%m/%Y"), record["seconds"] / 86400, "Sí" if work else "No",
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
    if last_row < 2:
        return
    ws.format(f"A2:A{last_row}", {"numberFormat": {"type": "TEXT"}})
    for col in ("B", "D"):
        ws.format(f"{col}2:{col}{last_row}", {"numberFormat": {"type": "TIME", "pattern": "[h]:mm:ss"}})


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

if st.button("🔄 Recargar Google Sheets"):
    refresh()

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
worked_hist = total(records,START,yesterday)
expected_hist = total(records,START,yesterday,"target")
worked_provisional = total(records,START,today)
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
    st.markdown("### Horas a recuperar")
    st.progress(1.0 if expected_hist==0 else min(1.0,worked_hist/expected_hist),
                text=f"Hasta ayer · {fmt(worked_hist)} trabajadas / {fmt(expected_hist)} obligatorias")
    with st.container(border=True):
        debt=expected_hist-worked_hist
        st.metric("Deuda oficial hasta ayer" if debt>=0 else "Horas a favor hasta ayer",fmt(abs(debt)))
        st.caption("Deuda negativa significa saldo a favor. El trabajo de hoy se incorpora mañana.")
        provisional=worked_provisional-expected_provisional
        st.metric("Balance provisional incluyendo hoy",("+" if provisional>=0 else "−")+fmt(abs(provisional)))
        with st.popover("Detalles por mes"):
            months=sorted({(d.year,d.month) for d in records if START<=d<=yesterday})
            for year,month in months:
                a=max(START,date(year,month,1))
                b=min(yesterday,date(year,month,calendar.monthrange(year,month)[1]))
                balance=total(records,a,b)-total(records,a,b,"target")
                st.write(f"**{MONTHS[month].capitalize()} {year}:** {'+' if balance>=0 else '−'}{fmt(abs(balance))}")

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
            data.append({"Fecha":d.strftime("%d/%m/%Y"),"Laborable":r["work"],
                         "Horas":r["seconds"]//3600,"Minutos":(r["seconds"]%3600)//60,
                         "Objetivo":fmt(DAILY_SECONDS if r["work"] else 0),
                         "Trabajado":fmt(r["seconds"]),"Motivo":r.get("note","")})
        df=pd.DataFrame(data)
        edited=st.data_editor(df,hide_index=True,use_container_width=True,key=f"editor_{year}_{month}",
            disabled=["Fecha","Objetivo","Trabajado"],
            column_config={"Laborable":st.column_config.CheckboxColumn("Laborable"),
                           "Horas":st.column_config.NumberColumn("Horas",min_value=0,max_value=1000,step=1),
                           "Minutos":st.column_config.NumberColumn("Minutos",min_value=0,max_value=59,step=1),
                           "Motivo":st.column_config.TextColumn("Motivo")})
        if st.button("Guardar cambios del historial",type="primary"):
            changes=[]
            for idx,d in enumerate(subset):
                old=records[d]
                new=edited.iloc[idx]
                new_secs=int(new["Horas"])*3600+int(new["Minutos"])*60
                if new_secs!=old["seconds"] or bool(new["Laborable"])!=old["work"] or str(new["Motivo"])!=old.get("note",""):
                    changes.append((d,new_secs,bool(new["Laborable"]),str(new["Motivo"])))
            try:
                for d,s,w,n in changes:
                    save_day(ws,records,d,seconds=s,work=w,note=n)
                st.success(f"{len(changes)} día(s) actualizado(s)")
                refresh()
            except Exception as exc:
                st.error(f"Error guardando historial: {exc}. Revisa la hoja antes de reintentar.")

if state[1]:
    time.sleep(1)
    st.rerun()
