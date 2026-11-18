"""Control de horas: Streamlit + Google Sheets. Una hoja visible."""
from __future__ import annotations

import calendar
import json
import re
import time
import tempfile
from pathlib import Path
import streamlit.components.v1 as components
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import gspread
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from caldav import DAVClient
from icalendar import Calendar as ICalendar, Event as IEvent
from uuid import uuid4
import hashlib
TIMELINE_HTML = '<!doctype html><html lang="es"><head><meta charset="utf-8"><style>\n:root{color-scheme:light dark}*{box-sizing:border-box}body{margin:0;padding:3px;font:13px system-ui,-apple-system,Segoe UI,sans-serif;color:var(--text-color,#263445);background:transparent}.panel{padding:14px;border:1px solid var(--secondary-background-color,#e4e8ee);border-radius:14px}.heading{display:flex;justify-content:space-between;gap:12px;align-items:center}.muted{font-size:11px;opacity:.72}.total{font-size:20px;font-weight:750}.axis{display:flex;justify-content:space-between;margin:17px 0 8px;font-size:10px;opacity:.7}.track{position:relative;height:44px;border-radius:9px;background:var(--secondary-background-color,#e8edf4);touch-action:none}.slot,.fixed{position:absolute;top:5px;height:34px;border-radius:7px;overflow:visible}.slot{background:var(--primary-color,#2563eb);cursor:grab;touch-action:none}.slot.active{outline:2px solid var(--text-color,#263445);outline-offset:2px}.fixed{background:#ec4899;cursor:not-allowed;z-index:1}.handle{position:absolute;top:1px;width:10px;height:32px;background:#fff7;border-radius:3px;cursor:ew-resize;touch-action:none}.handle.left{left:0}.handle.right{right:0}.slotlabel{text-align:center;line-height:34px;color:#fff;font-size:10px;white-space:nowrap;overflow:hidden;padding:0 10px;pointer-events:none}.legend{display:flex;gap:16px;flex-wrap:wrap;margin:10px 0;font-size:11px}.swatch{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:5px}.chips{display:flex;gap:6px;flex-wrap:wrap;min-height:32px;margin:10px 0}.chip,button{cursor:pointer;font:12px system-ui,sans-serif;color:var(--text-color,#263445);background:var(--secondary-background-color,#f1f4f8);border:1px solid #8b9baa55;border-radius:8px;padding:7px 10px}.chip.active{border-color:var(--primary-color,#2563eb);font-weight:700}button:disabled{opacity:.45;cursor:default}.actions{display:flex;gap:6px;flex-wrap:wrap;align-items:center}.spacer{flex:1}.save{background:var(--primary-color,#2563eb);border:0;color:#fff;font-weight:650}.status{margin-top:10px;min-height:16px;font-size:11px;opacity:.76}.error{color:#dc2626;font-size:11px;min-height:15px}.data{display:flex;gap:18px;flex-wrap:wrap;margin-top:12px}.data strong{display:block;font-size:16px}.data span{font-size:11px;opacity:.72}\n</style></head><body><div class="panel"><div class="heading"><div><strong>Franjas del día</strong><div class="muted">Rosa: realizado y fijo · Azul: previsto y editable · pasos de 15 minutos</div></div><div style="text-align:right"><div id="total" class="total">0 h 00 min</div><div class="muted">Planificado</div></div></div><div class="axis"><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span></div><div id="track" class="track"></div><div class="legend"><span><i class="swatch" style="background:#ec4899"></i>Realizado (inamovible)</span><span><i class="swatch" style="background:#3b82f6"></i>Planificado (editable)</span></div><div id="chips" class="chips"></div><div class="actions"><button id="add">+ Añadir</button><button id="remove">− Eliminar</button><button id="reset">Restablecer día</button><button id="default">Guardar como habitual</button><div class="spacer"></div><button id="save" class="save">Guardar cambios</button></div><div class="data"><div><span>Registrado en Sheets</span><strong id="worked">0 h 00 min</strong></div><div><span>Pendiente del objetivo diario</span><strong id="pending">0 h 00 min</strong></div><div><span>Franjas reales identificadas</span><strong id="fixedtotal">0 h 00 min</strong></div></div><div id="status" class="status">Sin cambios pendientes</div><div id="error" class="error"></div></div>\n<script>\nlet slots=[],fixed=[],active=-1,readonly=false,day=\'\',initialized=false,drag=null,base=[],dirty=false,mode=\'day\';let revision=\'\',maxQuarters=96;\nconst $=id=>document.getElementById(id);const fmt=n=>String(Math.floor(n/4)).padStart(2,\'0\')+\':\'+String(n%4*15).padStart(2,\'0\');const human=n=>Math.floor(n/60)+\' h \'+String(n%60).padStart(2,\'0\')+\' min\';const clone=x=>x.map(s=>s.slice());\nconst valid=arr=>Array.isArray(arr)&&arr.length<=20&&arr.every(s=>Array.isArray(s)&&s.length===2&&Number.isInteger(s[0])&&Number.isInteger(s[1])&&s[0]>=0&&s[1]<=96&&s[0]<s[1])&&arr.every((s,i)=>arr.every((t,j)=>i===j||s[1]<=t[0]||t[1]<=s[0]));\nconst overlap=(a,b)=>a.some(s=>b.some(t=>s[0]<t[1]&&t[0]<s[1]));const sum=x=>x.reduce((t,s)=>t+s[1]-s[0],0);\nfunction status(){ $(\'status\').textContent=dirty?\'Cambios sin guardar · pulsa Guardar cambios\':\'Sin cambios pendientes\';$(\'save\').disabled=readonly||!dirty;}\nfunction change(){dirty=true;mode=\'day\';status();$(\'error\').textContent=\'\';}\nfunction draw(){slots.sort((a,b)=>a[0]-b[0]);$(\'track\').innerHTML=\'\';$(\'chips\').innerHTML=\'\';\n fixed.forEach(s=>{let e=document.createElement(\'div\');e.className=\'fixed\';e.style.left=s[0]/96*100+\'%\';e.style.width=(s[1]-s[0])/96*100+\'%\';e.innerHTML=\'<div class="slotlabel">✓ \'+fmt(s[0])+\'–\'+fmt(s[1])+\'</div>\';e.title=\'Bloque realizado: fijo\';$(\'track\').appendChild(e)});\n slots.forEach((s,i)=>{let e=document.createElement(\'div\');e.className=\'slot\'+(active===i?\' active\':\'\');e.style.left=s[0]/96*100+\'%\';e.style.width=(s[1]-s[0])/96*100+\'%\';e.innerHTML=\'<div class="handle left" data-edge="start"></div><div class="slotlabel">\'+fmt(s[0])+\'–\'+fmt(s[1])+\'</div><div class="handle right" data-edge="end"></div>\';\n e.addEventListener(\'pointerdown\',ev=>{if(readonly)return;active=i;drag={i,edge:ev.target.dataset.edge||\'move\',x:ev.clientX,orig:s.slice(),pointer:ev.pointerId};e.setPointerCapture(ev.pointerId);ev.preventDefault();});\n e.addEventListener(\'pointermove\',ev=>{if(!drag||drag.i!==i||drag.pointer!==ev.pointerId)return;let width=$(\'track\').getBoundingClientRect().width,delta=Math.round((ev.clientX-drag.x)/width*96),a=drag.orig.slice();if(drag.edge===\'start\')a[0]=Math.max(0,Math.min(a[1]-1,a[0]+delta));else if(drag.edge===\'end\')a[1]=Math.min(96,Math.max(a[0]+1,a[1]+delta));else{let len=a[1]-a[0];a[0]=Math.max(0,Math.min(96-len,a[0]+delta));a[1]=a[0]+len}let next=clone(slots);next[i]=a;if(valid(next)&&!overlap(next,fixed)){slots[i]=a;e.style.left=a[0]/96*100+\'%\';e.style.width=(a[1]-a[0])/96*100+\'%\';e.querySelector(\'.slotlabel\').textContent=fmt(a[0])+\'–\'+fmt(a[1]);$(\'total\').textContent=human(sum(slots)*15);change();}});\n e.addEventListener(\'pointerup\',()=>{if(drag&&drag.i===i){drag=null;draw()}});e.addEventListener(\'pointercancel\',()=>{drag=null;draw()});$(\'track\').appendChild(e);let c=document.createElement(\'button\');c.className=\'chip\'+(active===i?\' active\':\'\');c.textContent=fmt(s[0])+\'–\'+fmt(s[1]);c.onclick=()=>{active=i;draw()};$(\'chips\').appendChild(c)});\n $(\'total\').textContent=human(sum(slots)*15);$(\'fixedtotal\').textContent=human(sum(fixed)*15);$(\'remove\').disabled=readonly||active<0||active>=slots.length;for(let key of [\'add\',\'reset\',\'default\'])$(key).disabled=readonly;status();}\n $(\'add\').onclick=()=>{for(let a=32;a<=92;a++){let x=[a,a+4];if(valid([...slots,x])&&!overlap([...slots,x],fixed)&&sum([...slots,x])+sum(fixed)<=maxQuarters){slots.push(x);active=slots.length-1;change();draw();return}}$(\'error\').textContent=\'No cabe otra franja de una hora sin solaparse o exceder el límite.\'};\n $(\'remove\').onclick=()=>{if(active<0)return;slots.splice(active,1);active=slots.length?0:-1;change();draw()};\n $(\'reset\').onclick=()=>{slots=clone(base);slots=trim(slots,fixed);active=slots.length?0:-1;mode=\'reset\';dirty=true;draw()};\n $(\'default\').onclick=()=>{if(readonly)return;mode=\'default\';dirty=true;status();$(\'status\').textContent=\'Se guardará como horario habitual al pulsar Guardar cambios\'};\n function trim(arr,ex){let out=[];for(const [a,b] of arr){let pieces=[[a,b]];for(const [x,y] of ex){let next=[];for(const [m,n] of pieces){if(n<=x||m>=y)next.push([m,n]);else{if(m<x)next.push([m,x]);if(y<n)next.push([y,n]);}}pieces=next;}out.push(...pieces)}return out.filter(s=>s[0]<s[1]);}\n $(\'save\').onclick=()=>{if(!dirty||readonly)return;if(!valid(slots)||overlap(slots,fixed)||sum(slots)+sum(fixed)>maxQuarters){$(\'error\').textContent=\'Hay solapamiento o se supera el máximo del día\';return}window.parent.postMessage({isStreamlitMessage:true,type:\'streamlit:setComponentValue\',value:{day,slots:clone(slots),mode}},\'*\');$(\'save\').disabled=true;$(\'status\').textContent=\'Guardando…\'};\n window.addEventListener(\'message\',e=>{if(e.data.type!==\'streamlit:render\')return;const a=e.data.args||{};const theme=e.data.theme||a.theme||{};for(const [key,css] of [[\'primaryColor\',\'--primary-color\'],[\'backgroundColor\',\'--background-color\'],[\'secondaryBackgroundColor\',\'--secondary-background-color\'],[\'textColor\',\'--text-color\']]){if(theme[key])document.documentElement.style.setProperty(css,theme[key])}if(!initialized||day!==a.day||revision!==a.revision){day=a.day;revision=a.revision;slots=clone(a.slots||[]);fixed=clone(a.fixed||[]);base=clone(a.base||[]);readonly=!!a.readonly;maxQuarters=a.max_quarters||96;active=slots.length?0:-1;dirty=false;mode=\'day\';initialized=true;draw()}$(\'worked\').textContent=human(a.worked_seconds/60||0);$(\'pending\').textContent=human(a.pending_seconds/60||0)});\n window.parent.postMessage({isStreamlitMessage:true,type:\'streamlit:componentReady\',apiVersion:1},\'*\');window.parent.postMessage({isStreamlitMessage:true,type:\'streamlit:setFrameHeight\',height:300},\'*\');\n</script></body></html>'

st.set_page_config(page_title="Control horas work", page_icon="https://cdn-icons-png.flaticon.com/512/194/194978.png", layout="wide")
st.markdown('''<style>
html,body,[class*="css"]{font-size:18px!important}
[data-testid="stMetricValue"]{font-size:1.8rem!important}
[data-testid="stMetricLabel"]{font-size:1.1rem!important}
/* Fondo oscuro en las barras nativas; el relleno conserva su color. */
div[data-testid="stProgress"] [role="progressbar"],
div[data-testid="stProgress"]>div>div{background-color:#08090d!important}
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

def obtener_calendario_icloud():
    with DAVClient(
        url="https://caldav.icloud.com/",
        username=st.secrets["icloud"]["apple_id"],
        password=st.secrets["icloud"]["app_password"],
    ) as cliente:

        calendarios = cliente.principal().get_calendars()

        for calendario in calendarios:
            if calendario.get_display_name() == "Trabajo":
                return str(calendario.url)

    raise RuntimeError("No se encontró el calendario Trabajo")


# iCloud es la fuente de verdad de las franjas sincronizadas. Solo se gestionan
# eventos que contienen nuestra marca; el resto del calendario no se toca.
ICLOUD_MARKER = "STREAMLIT_CONTROL_HORAS_V1"


def icloud_calendar():
    client = DAVClient(
        url="https://caldav.icloud.com/",
        username=st.secrets["icloud"]["apple_id"],
        password=st.secrets["icloud"]["app_password"],
    )
    try:
        name = st.secrets["icloud"].get("calendar_name", "Trabajo")
        matches = [c for c in client.principal().get_calendars()
                   if c.get_display_name() == name]
        if len(matches) != 1:
            raise ValueError(f"Se esperaban 1 calendario llamado {name!r}; encontrados {len(matches)}")
        return client, matches[0]
    except Exception:
        client.close()
        raise


def event_bounds(vevent):
    start = vevent.decoded("DTSTART")
    end = vevent.decoded("DTEND")
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return None  # Los eventos de día completo no son franjas.
    if start.tzinfo is None:
        start = start.replace(tzinfo=TZ)
    if end.tzinfo is None:
        end = end.replace(tzinfo=TZ)
    return start.astimezone(TZ), end.astimezone(TZ)


def icloud_events(day, cal):
    start = datetime(day.year, day.month, day.day, tzinfo=TZ)
    end = start + timedelta(days=1)
    result = []
    for resource in cal.date_search(start=start, end=end, expand=False):
        parsed = ICalendar.from_ical(resource.data)
        for component in parsed.walk("VEVENT"):
            if str(component.get("X-STREAMLIT-HORAS", "")) != ICLOUD_MARKER:
                continue
            bounds = event_bounds(component)
            if bounds is None:
                continue
            a, b = bounds
            # No alterar eventos recurrentes ni franjas que crucen medianoche.
            if component.get("RRULE") or component.get("RECURRENCE-ID"):
                raise ValueError("Hay un evento gestionado recurrente; requiere revisión manual")
            if a.date() != day or b.date() != day:
                continue
            if a.second or b.second or a.minute % 15 or b.minute % 15:
                raise ValueError("Hay franjas iCloud fuera de los pasos de 15 min")
            first, last = a.hour * 4 + a.minute // 15, b.hour * 4 + b.minute // 15
            result.append((first, last, resource, parsed, component))
    result.sort(key=lambda x: (x[0], x[1]))
    normalize_slots([[a, b] for a, b, *_ in result])
    return result


def icloud_fingerprint(events):
    # Incluye los datos de cada evento para detectar modificaciones concurrentes.
    raw = "|".join(sorted(str(x[2].data) for x in events))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_icloud_event(cal, day, a, b):
    start = datetime(day.year, day.month, day.day, tzinfo=TZ)
    event = IEvent()
    event.add("uid", f"{uuid4()}@streamlit-control-horas")
    event.add("summary", "Trabajo planificado")
    event.add("dtstart", start + timedelta(minutes=a * 15))
    event.add("dtend", start + timedelta(minutes=b * 15))
    event.add("dtstamp", datetime.now(ZoneInfo("UTC")))
    event.add("X-STREAMLIT-HORAS", ICLOUD_MARKER)
    calobj = ICalendar()
    calobj.add("prodid", "-//Control Horas Streamlit//ES")
    calobj.add("version", "2.0")
    calobj.add_component(event)
    cal.save_event(calobj.to_ical().decode("utf-8"))


def update_icloud_event(resource, parsed, component, day, a, b):
    start = datetime(day.year, day.month, day.day, tzinfo=TZ)
    component.pop("DTSTART", None)
    component.pop("DTEND", None)
    component.add("dtstart", start + timedelta(minutes=a * 15))
    component.add("dtend", start + timedelta(minutes=b * 15))
    resource.data = parsed.to_ical().decode("utf-8")
    resource.save()


def save_icloud_slots(cal, day, previous, desired):
    # Actualiza los eventos existentes en orden, crea los adicionales y elimina
    # únicamente los sobrantes que tengan nuestra marca.
    for i, (a, b) in enumerate(desired):
        if i < len(previous):
            old_a, old_b, resource, parsed, component = previous[i]
            if (a, b) != (old_a, old_b):
                update_icloud_event(resource, parsed, component, day, a, b)
        else:
            create_icloud_event(cal, day, a, b)
    for old in previous[len(desired):]:
        old[2].delete()


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


def period_on_track(actual, required_to_date):
    """El rosa significa estar al dia, no necesariamente haber terminado el periodo."""
    return actual >= required_to_date


def period_progress(actual, full_target):
    """La longitud de la barra sigue referida al objetivo de todo el periodo."""
    return 1.0 if full_target <= 0 else max(0.0, min(1.0, actual / full_target))


def progress_period(actual, full_target, on_track):
    """Barra aislada: el color no depende de las otras barras de Streamlit."""
    percentage = period_progress(actual, full_target) * 100
    gradient = ("#ec4899,#be185d,#f472b6" if on_track
                else "#3b82f6,#1d4ed8,#60a5fa")
    st.markdown(
        '<div style="margin:0 0 8px">'
        f'<div style="font-size:.88rem;margin-bottom:6px">Objetivo: {int(percentage)} %</div>'
        '<div role="progressbar" aria-label="Progreso de horas" '
        f'aria-valuenow="{int(percentage)}" aria-valuemin="0" aria-valuemax="100" '
        'style="height:12px;border-radius:999px;background:#08090d;overflow:hidden">'
        f'<div style="width:{percentage:.4f}%;height:100%;border-radius:999px;'
        f'background:linear-gradient(90deg,{gradient});'
        'transition:width .6s ease-in-out"></div></div></div>',
        unsafe_allow_html=True,
    )


def plot_ring(actual, target, on_track=False):
    """Porcentaje real del periodo, coloreado segun el cumplimiento hasta hoy."""
    fig, ax = plt.subplots(figsize=(2.2, 2.2))
    fig.patch.set_facecolor("none")
    ax.set_facecolor("none")
    progress = period_progress(actual, target)
    active_color = "#ec4899" if on_track else "#3b82f6"
    if progress >= 1:
        vals, colors = [1], [active_color]
    elif progress <= 0:
        vals, colors = [1], ["#334155"]
    else:
        vals, colors = [progress, 1 - progress], [active_color, "#334155"]
    ax.pie(vals, colors=colors, startangle=90,
           wedgeprops={"width": .4, "edgecolor": "none"})
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


# Fase 4: preferencias de secciones, almacenadas fuera de los registros de horas.
# P:Q = intervalos reales; R:S = visibilidad. No se alteran A:G, I:J ni M:N.
SECTION_NAMES = {
    "cronometro": "Cronometro y registro manual",
    "resumen": "Resumen y graficas de progreso",
    "balance": "Balance de horas y deuda",
    "historial": "Historial de horas trabajadas",
    "herramientas": "Herramientas de Google Sheets",
    "icloud": "Prueba de conexion con iCloud",
    "horario": "Horario de trabajo",
}


def read_section_preferences(sheet):
    rows = sheet.get("R1:S2")
    values = {r[0]: r[1] for r in rows if len(r) > 1}
    raw = values.get("Secciones visibles", "")
    if not raw:
        return {key: True for key in SECTION_NAMES}
    settings = json.loads(raw)
    if not isinstance(settings, dict):
        raise ValueError("La configuracion guardada no es un objeto")
    if any(type(v) is not bool for v in settings.values()):
        raise ValueError("Las preferencias deben ser verdadero/falso")
    return {key: settings.get(key, True) for key in SECTION_NAMES}


def save_section_preferences(sheet, preferences, previous):
    if read_section_preferences(sheet) != previous:
        raise ValueError("Las preferencias cambiaron en otra pestana. Recarga antes de guardarlas")
    saved = {key: bool(preferences[key]) for key in SECTION_NAMES}
    sheet.update(range_name="R1:S2", values=[
        ["Preferencias interfaz", "v1"],
        ["Secciones visibles", json.dumps(saved, ensure_ascii=False, sort_keys=True)],
    ], value_input_option="RAW")


# El menu de visibilidad queda SIEMPRE disponible, aunque se oculten todos los bloques.
try:
    section_preferences = read_section_preferences(ws)
    section_config_ok = True
except Exception as exc:
    section_config_ok = False
    section_preferences = {key: True for key in SECTION_NAMES}
    st.warning(f"No se pueden leer las preferencias de visibilidad: {exc}. Se muestran todas las secciones por seguridad.")

# Boton compacto: el formulario solo ocupa espacio al abrir el menu.
visibility_button_col, _visibility_rest_col = st.columns([1.25, 6], gap="small")
with visibility_button_col:
    visibility_popover = st.popover("⚙️ Secciones", help="Mostrar u ocultar partes de la pagina")
with visibility_popover:
    st.caption("Elige los bloques que quieres ver y pulsa Guardar. La seleccion se conserva en Google Sheets al recargar o cambiar de dispositivo. No se elimina ningun dato.")
    with st.form("form_section_preferences"):
        chosen_visibility = {}
        cols = st.columns(2)
        for index, (section_id, section_title) in enumerate(SECTION_NAMES.items()):
            with cols[index % 2]:
                chosen_visibility[section_id] = st.checkbox(
                    section_title, value=section_preferences[section_id],
                    key=f"pref_section_{section_id}",
                )
        save_sections = st.form_submit_button(
            "Guardar secciones visibles", width="stretch", disabled=not section_config_ok
        )
    if save_sections:
        try:
            save_section_preferences(ws, chosen_visibility, section_preferences)
            st.toast("Preferencias de secciones guardadas")
            st.rerun()
        except Exception as exc:
            st.error(f"No se pudo guardar la visibilidad: {exc}")
    if st.button("Mostrar todas las secciones", key="show_all_sections", disabled=not section_config_ok):
        try:
            save_section_preferences(ws, {k: True for k in SECTION_NAMES}, section_preferences)
            st.rerun()
        except Exception as exc:
            st.error(f"No se pudieron restaurar las secciones: {exc}")


def show_section(section_id):
    return section_preferences[section_id]

today = now().date()
yesterday = today-timedelta(days=1)
week_start = today-timedelta(days=today.weekday())
week_end = week_start + timedelta(days=6)
month_start = today.replace(day=1)
month_end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])

def full_period_target(records, first, last):
    """Objetivo de todo el periodo, incluso para fechas futuras sin fila en Sheets."""
    target_seconds = 0
    for day in date_range(max(first, START), last):
        if day in records:
            is_workday = records[day]["work"]
        else:
            is_workday, _ = default_workday(day)
        if is_workday:
            target_seconds += DAILY_SECONDS
    return target_seconds
worked_today = total(records,today,today)
worked_week = total(records,week_start,today)
worked_month = total(records,month_start,today)
expected_today = total(records,today,today,"target")
expected_week = full_period_target(records,week_start,week_end)
expected_month = full_period_target(records,month_start,month_end)
# Umbrales hasta hoy (distintos de los objetivos completos mostrados en las barras).
expected_week_to_date = full_period_target(records,week_start,today)
expected_month_to_date = full_period_target(records,month_start,today)
worked_hist = sum(r["seconds"] for d,r in records.items() if d <= yesterday)
expected_hist = total(records,START,yesterday,"target")
worked_provisional = sum(r["seconds"] for d,r in records.items() if d <= today)
expected_provisional = total(records,START,today,"target")

# Plan de recuperacion: se recalcula con el saldo REAL de la hoja en cada carga.
DEADLINE = date(2026, 12, 15)
SATURDAY_LIMIT = 2 * 3600
PLAN_STEP = 5 * 60


def planned_workday(day, records):
    """No planificar domingos, festivos ni dias marcados no laborables."""
    if day.weekday() == 6 or holiday_name(day):
        return False
    if day.weekday() == 5:
        return True  # Sabados opcionales: maximo dos horas.
    return records[day]["work"] if day in records else default_workday(day)[0]


def recovery_plan(records, today, deadline, historical_debt):
    """Plan sin duplicar las horas ya registradas hoy o anteriormente."""
    if today > deadline:
        return None
    days = date_range(today, deadline)
    # Deuda hasta ayer + obligaciones desde hoy hasta la fecha limite.
    future_obligation = sum(DAILY_SECONDS for d in days
                            if (records[d]["work"] if d in records else default_workday(d)[0]))
    already_worked = sum(records.get(d, {}).get("seconds", 0) for d in days)
    required = max(0, historical_debt + future_obligation - already_worked)
    weekdays = [d for d in days if d.weekday() < 5 and planned_workday(d, records)]
    saturdays = [d for d in days if d.weekday() == 5 and planned_workday(d, records)]
    saturday_capacity = len(saturdays) * SATURDAY_LIMIT
    weekday_target = (max(0, required - saturday_capacity) + len(weekdays) - 1) // len(weekdays) if weekdays else 0
    weekday_target = ((weekday_target + PLAN_STEP - 1) // PLAN_STEP) * PLAN_STEP
    # El sabado solo se usa si hace falta para llegar a la fecha limite.
    remaining_after_weekdays = max(0, required - weekday_target * len(weekdays))
    saturday_target = min(SATURDAY_LIMIT, ((remaining_after_weekdays + len(saturdays) - 1) // len(saturdays) + PLAN_STEP - 1) // PLAN_STEP * PLAN_STEP) if saturdays and remaining_after_weekdays else 0
    planned = []
    for d in days:
        worked = records.get(d, {}).get("seconds", 0)
        if d.weekday() == 6:
            target, label = 0, "Domingo libre"
        elif holiday_name(d):
            target, label = 0, "Festivo: " + holiday_name(d)
        elif not planned_workday(d, records):
            target, label = 0, "No laborable / vacaciones"
        elif d.weekday() == 5:
            target, label = saturday_target, "Sabado (max. 2 h)"
        else:
            target, label = weekday_target, "Lunes a viernes"
        pending = max(0, target - worked)
        planned.append({"Fecha": d.strftime("%d/%m/%Y"),
                        "Dia": ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"][d.weekday()],
                        "Horario recomendado": ("09:00-12:30 / 13:15-" + (datetime(2026, 1, 1, 13, 15) + timedelta(seconds=max(0, target - 3*3600 - 30*60))).strftime("%H:%M")) if d.weekday() < 5 and target >= 3*3600+30*60 else ("10:00-" + (datetime(2026, 1, 1, 10) + timedelta(seconds=target)).strftime("%H:%M") if target else "Descanso"),
                        "Objetivo": fmt(target), "Registrado": fmt(worked),
                        "Pendiente": fmt(pending), "Tipo": label,
                        "_target": target, "_worked": worked})
    capacity = sum(x["_target"] for x in planned)
    return planned, required, weekday_target, saturday_target, capacity



# Planificador visual: preferencias en M:N de la MISMA hoja.
# No modifica las horas trabajadas ni las formulas de la tabla principal.
def normalize_slots(value):
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("Numero de franjas incorrecto")
    slots = []
    for item in value:
        if (not isinstance(item, list) or len(item) != 2 or
                any(type(n) is not int for n in item)):
            raise ValueError("Franja invalida")
        a, b = item
        if not 0 <= a < b <= 96:
            raise ValueError("Franjas fuera del dia")
        slots.append([a, b])
    slots.sort()
    if any(slots[i][1] > slots[i+1][0] for i in range(len(slots)-1)):
        raise ValueError("Las franjas no pueden solaparse")
    return slots


def read_schedule(ws):
    cells = ws.get("M1:N3")
    data = {r[0]: r[1] for r in cells if len(r) > 1}
    try:
        base = normalize_slots(json.loads(data.get("Horario habitual", "[[36,50],[53,64]]")))
        exceptions = json.loads(data.get("Excepciones", "{}"))
        if not isinstance(exceptions, dict):
            raise ValueError("Excepciones invalidas")
        exceptions = {k: normalize_slots(v) for k,v in exceptions.items()}
        return base, exceptions
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Horario guardado no valido: {exc}") from exc


def write_schedule(ws, base, exceptions):
    ws.update(range_name="M1:N3", values=[
        ["Planificador", "v1"],
        ["Horario habitual", json.dumps(base)],
        ["Excepciones", json.dumps(exceptions, ensure_ascii=False)]],
        value_input_option="RAW")


def schedule_for_day(day, base, exceptions):
    if day.isoformat() in exceptions:
        return exceptions[day.isoformat()]
    if day.weekday() == 6 or holiday_name(day):
        return []
    if day.weekday() == 5:
        return [[40, 48]]  # Sabado 10:00-12:00
    return base


# Fase 3: intervalos REALES con hora conocida. Guardados fuera de A:N.
# No se deducen intervalos de una duracion total: esa inferencia seria incorrecta.
def read_real_intervals(ws):
    cells = ws.get("P1:Q2")
    data = {row[0]: row[1] for row in cells if len(row) > 1}
    try:
        raw = json.loads(data.get("Intervalos reales", "{}"))
        if not isinstance(raw, dict):
            raise ValueError("Formato de intervalos reales no valido")
        return {str(day): normalize_slots(slots) for day, slots in raw.items()}
    except (ValueError, TypeError) as exc:
        raise ValueError(f"No se pudieron leer los intervalos reales: {exc}") from exc


def save_real_intervals(ws, intervals, previous):
    # Proteccion contra otra pestana editando las mismas horas.
    if read_real_intervals(ws) != previous:
        raise ValueError("Los intervalos cambiaron en otra sesion: recarga la pagina")
    ws.update(range_name="P1:Q2", values=[
        ["Planificador real", "v1"],
        ["Intervalos reales", json.dumps(intervals, ensure_ascii=False, sort_keys=True)]
    ], value_input_option="RAW")


def clock_quarter(value):
    return value.hour * 4 + value.minute // 15


def quarter_label(q):
    return f"{q//4:02d}:{(q%4)*15:02d}"


def strip_fixed(planned, fixed):
    """Divide los bloques previstos que se solapan con los reales."""
    out = []
    for a, b in planned:
        pieces = [(a, b)]
        for fa, fb in fixed:
            next_pieces = []
            for x, y in pieces:
                if y <= fa or x >= fb:
                    next_pieces.append((x, y))
                else:
                    if x < fa:
                        next_pieces.append((x, fa))
                    if fb < y:
                        next_pieces.append((fb, y))
            pieces = next_pieces
        out += [[x, y] for x, y in pieces if x < y]
    return normalize_slots(out)


@st.cache_resource
def timeline_component():
    # HTML embebido en app.py para desplegar un unico archivo en GitHub.
    folder = Path(tempfile.gettempdir()) / "control_horas_timeline_v3"
    folder.mkdir(parents=True, exist_ok=True)
    html = TIMELINE_HTML
    (folder / "index.html").write_text(html, encoding="utf-8")
    return components.declare_component("control_horas_timeline_v3", path=str(folder))


if any(show_section(x) for x in ("cronometro", "resumen", "balance", "historial")):
    left, right = st.columns([1.1, .9])
else:
    left = right = st.container()
with left:
    if show_section("cronometro"):
        st.markdown("### Cronómetro y Registro de Horas")
        with st.container(border=True):
            elapsed = timer_seconds(state)
            st.markdown(f"### ⏱️ {fmt_clock(elapsed)}")
            a,b,c = st.columns(3)
            with a:
                if not state[1] and st.button("Activar", type="primary", width="stretch"):
                    timer_write(ws,state[0],True,now());refresh()
                if state[1] and st.button("Pausar",width="stretch"):
                    timer_write(ws,elapsed,False,None);refresh()
            with b:
                if st.button("Resetear",width="stretch"):
                    timer_write(ws,0,False,None);refresh()
            with c:
                if st.button("Registrar crono",width="stretch"):
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
                submitted = st.form_submit_button("Registrar",width="stretch")
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

    if show_section("resumen"):
        if show_section("cronometro"):
            st.divider()
        st.markdown("### Resumen actual")
        cols = st.columns(3)
        for col,label,actual,target,required,caption in zip(
                cols, ["Hoy", "Semana", "Mes"],
                [worked_today, worked_week, worked_month],
                [expected_today, expected_week, expected_month],
                [expected_today, expected_week_to_date, expected_month_to_date],
                [today.strftime("%d/%m/%Y"), f"Desde {week_start:%d/%m}", f"Desde {month_start:%d/%m}"]):
            with col:
                on_track = period_on_track(actual, required)
                progress_period(actual, target, on_track)
                with st.container(border=True):
                    st.metric(label, fmt(actual))
                    st.caption(f"{caption} · Meta completa: {fmt(target)}")
                    st.caption(f"Exigido hasta hoy: {fmt(required)} · "
                               + ("Al día ✓" if on_track else "Por debajo del objetivo"))
                fig = plot_ring(actual, target, on_track)
                st.pyplot(fig, width="stretch")
                plt.close(fig)
        st.caption("Rosa: alcanzado el objetivo acumulado hasta hoy. Azul: todavía por debajo. "
                   "La longitud representa el progreso sobre el objetivo completo de semana o mes. "
                   "Se descuentan los festivos y días no laborables. "
                   "La deuda sigue calculándose solo hasta ayer.")

with right:
    if show_section("balance"):
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

    if show_section("historial"):
        if show_section("balance"):
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
                        if st.button("⬅ Mover a la izquierda", width="stretch"):
                            order = st.session_state[layout_key].copy()
                            idx = order.index(move_col)
                            if idx > 0:
                                order[idx-1], order[idx] = order[idx], order[idx-1]
                                persist_layout(order)
                                st.rerun()
                    with down:
                        if st.button("Mover a la derecha ➡", width="stretch"):
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
            st.data_editor(df,hide_index=True,width="stretch",key=editor_key,
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


if show_section("herramientas"):
    if any(show_section(x) for x in ("cronometro", "resumen", "balance", "historial")):
        st.divider()
    st.markdown("### Herramientas de Google Sheets")
    actions_a, actions_b, actions_c = st.columns(3)
    with actions_a:
        if st.button("🔄 Recargar Google Sheets", width="stretch"):
            refresh()
    with actions_b:
        spreadsheet_id = st.secrets.get("spreadsheet_id", "1FuKT6RSIbmgQlr7LdSiYBHkuMguhfN4Yd_8OPsdCt6E")
        st.link_button("📊 Google Sheets", f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit", width="stretch")
    with actions_c:
        if st.button("🛠 Reparar formato y motivos de la hoja", width="stretch"):
            try:
                repair_sheet(ws, records)
                st.success("Formato y motivos corregidos. Recargando...")
                refresh()
            except Exception as exc:
                st.error(f"No se pudo reparar la hoja: {exc}")

# Sin recarga completa cada segundo: evita pantalla en blanco con cronometro activo.


if show_section("icloud"):
    if any(show_section(x) for x in ("cronometro", "resumen", "balance", "historial", "herramientas")):
        st.divider()
    st.subheader("Prueba de conexión con iCloud")

    if st.button("Comprobar conexión con iCloud"):
        try:
            obtener_calendario_icloud()
            st.success("Conexión correcta. Calendario Trabajo encontrado.")
        except Exception:
            st.error(
                "No se ha podido conectar con el calendario Trabajo. "
                "Revisa las credenciales y el nombre del calendario."
            )

if show_section("horario"):
    if any(show_section(x) for x in ("cronometro", "resumen", "balance", "historial", "herramientas", "icloud")):
        st.divider()
    st.markdown("### Mi horario de trabajo")
    st.caption("Rosa: franjas reales fijas · Azul: franjas previstas editables. Solo el horario previsto se sincroniza con iCloud.")
    try:
        schedule_base, schedule_exceptions = read_schedule(ws)
        real_intervals = read_real_intervals(ws)
    except Exception as exc:
        st.error(f"No se pudo leer el planificador: {exc}")
    else:
        schedule_col, _unused = st.columns([3, 2])
        with schedule_col:
            chosen_day = st.date_input("Día del horario", value=today,
                                       min_value=date(2026, 1, 1),
                                       max_value=date(2027, 12, 31),
                                       key="schedule_date")
            is_rest = bool(chosen_day.weekday() == 6 or holiday_name(chosen_day))
            if is_rest:
                st.info("Este día es domingo o festivo: se mantiene como descanso y no se puede programar trabajo.")
            elif chosen_day.weekday() == 5:
                st.caption("Sábado: máximo 2 horas en total.")
            elif chosen_day in records and not records[chosen_day]["work"]:
                st.warning("Este día figura como no laborable en el historial. El horario planificado no cambia esa condición.")
            fixed_slots = real_intervals.get(chosen_day.isoformat(), [])
            # La tabla A:G guarda totales, no horas exactas. Las franjas reales se
            # añaden sin sumar otra vez horas ni modificar la deuda.
            with st.expander("Registrar franjas reales ya trabajadas", expanded=False):
                st.caption("Indica el intervalo real. Se dibujará en rosa y quedará bloqueado. No suma horas al historial: utiliza el registro de horas existente para eso.")
                with st.form("new_fixed_slot"):
                    f1, f2 = st.columns(2)
                    with f1:
                        real_start = st.time_input("Inicio real", value=datetime.strptime("08:00", "%H:%M").time(), step=900)
                    with f2:
                        real_end = st.time_input("Fin real", value=datetime.strptime("10:00", "%H:%M").time(), step=900)
                    submitted_real = st.form_submit_button("Fijar intervalo realizado")
                if submitted_real:
                    try:
                        a, b = clock_quarter(real_start), clock_quarter(real_end)
                        if real_start.minute % 15 or real_end.minute % 15 or a >= b:
                            raise ValueError("Selecciona horas crecientes en pasos de 15 minutos")
                        proposed = normalize_slots(fixed_slots + [[a, b]])
                        changed = dict(real_intervals)
                        changed[chosen_day.isoformat()] = proposed
                        save_real_intervals(ws, changed, real_intervals)
                        st.success("Franja real guardada, sin modificar las horas contabilizadas")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"No se pudo fijar la franja: {exc}")
                if fixed_slots:
                    st.write("Franjas fijadas: " + ", ".join(f"{quarter_label(a)}–{quarter_label(b)}" for a, b in fixed_slots))
                    st.caption("Los intervalos existentes se mantienen fijos. Puedes corregirlos eliminándolos aquí, sin cambiar el historial de horas.")
                    index_remove = st.selectbox("Corregir intervalo", range(len(fixed_slots)), format_func=lambda i: f"{quarter_label(fixed_slots[i][0])}–{quarter_label(fixed_slots[i][1])}")
                    if st.button("Eliminar intervalo seleccionado", key=f"remove_fixed_{chosen_day}"):
                        try:
                            changed = dict(real_intervals)
                            remainder = [x for i, x in enumerate(fixed_slots) if i != index_remove]
                            if remainder:
                                changed[chosen_day.isoformat()] = remainder
                            else:
                                changed.pop(chosen_day.isoformat(), None)
                            save_real_intervals(ws, changed, real_intervals)
                            st.rerun()
                        except Exception as exc:
                            st.error(f"No se pudo eliminar: {exc}")
            actual_seconds = records.get(chosen_day, {}).get("seconds", 0)
            target_seconds = DAILY_SECONDS if records.get(chosen_day, {}).get("work", default_workday(chosen_day)[0]) else 0
            st.caption(f"Horas trabajadas: {fmt(actual_seconds)} · Para el objetivo diario faltan: {fmt(max(0, target_seconds - actual_seconds))}")
            if abs(sum((b-a)*900 for a,b in fixed_slots) - actual_seconds) > 900 and fixed_slots:
                st.info("La duración de los bloques rosas no coincide con el total registrado: puede haber horas sin horario exacto identificado.")
            icloud_enabled = st.checkbox(
                "Sincronizar este horario con iCloud · Trabajo",
                value=False,
                help="Actívalo para consultar y guardar eventos de este día en iCloud. Solo se modificarán eventos creados por este planificador.",
                key="icloud_sync_enabled",
            )
            cloud_events = None
            cloud_signature = None
            cloud_error = None
            if icloud_enabled:
                try:
                    cloud_client, cloud_cal = icloud_calendar()
                    try:
                        cloud_events = icloud_events(chosen_day, cloud_cal)
                        cloud_signature = icloud_fingerprint(cloud_events)
                    finally:
                        cloud_client.close()
                except Exception as exc:
                    cloud_error = str(exc)
                    st.error(f"No se pudo leer iCloud: {cloud_error}. No se permitirá guardar en modo iCloud.")
            current_slots = schedule_for_day(chosen_day, schedule_base, schedule_exceptions)
            if cloud_events is not None:
                # Si ya hay eventos gestionados, iCloud prevalece sobre Sheets.
                # Sin eventos, se ofrece el horario habitual como borrador inicial.
                if cloud_events:
                    current_slots = [[a, b] for a, b, *_ in cloud_events]
                st.caption(f"iCloud: {len(cloud_events)} franja(s) sincronizada(s). Si no hay ninguna, se muestra el horario habitual como borrador. Los eventos ajenos no se modifican.")
            # Solo mostrar como editables las porciones no realizadas.
            current_slots = strip_fixed(current_slots, fixed_slots)
            # Un valor del componente se aplica solo una vez y solo a su fecha.
            timeline = timeline_component()
            revision = json.dumps([chosen_day.isoformat(), current_slots, fixed_slots, cloud_signature, icloud_enabled], ensure_ascii=False)
            event = timeline(day=chosen_day.isoformat(), slots=current_slots, fixed=fixed_slots,
                             worked_seconds=actual_seconds, pending_seconds=max(0, target_seconds - actual_seconds),
                             base=strip_fixed(schedule_for_day(chosen_day, schedule_base, {k:v for k,v in schedule_exceptions.items() if k != chosen_day.isoformat()}), fixed_slots), readonly=(is_rest or (icloud_enabled and cloud_error is not None)), max_quarters=(8 if chosen_day.weekday() == 5 else 96), revision=revision,
                             key=f"timeline_{chosen_day.isoformat()}", default=None)
            if event is not None and isinstance(event, dict):
                signature = json.dumps(event, sort_keys=True)
                event_key = f"schedule_last_event_{chosen_day.isoformat()}"
                if st.session_state.get(event_key) != signature:
                    try:
                        if event.get("day") != chosen_day.isoformat():
                            raise ValueError("La fecha del cambio no coincide")
                        mode = event.get("mode")
                        if mode not in ("day", "default", "reset"):
                            raise ValueError("Operacion no reconocida")
                        if is_rest:
                            raise ValueError("No se puede trabajar en festivos o domingos")
                        new_slots = normalize_slots(event.get("slots", []))
                        if strip_fixed(new_slots, fixed_slots) != new_slots:
                            raise ValueError("Los horarios previstos no pueden solaparse con los bloques reales")
                        if read_real_intervals(ws) != real_intervals:
                            raise ValueError("Las franjas reales cambiaron. Recarga para continuar")
                        if chosen_day.weekday() == 5 and sum(b-a for a,b in new_slots + fixed_slots) > 8:
                            raise ValueError("Los sabados no pueden superar 2 horas")
                        # Comprobar que la configuracion no ha cambiado en otra sesion.
                        latest_base, latest_exceptions = read_schedule(ws)
                        if latest_base != schedule_base or latest_exceptions != schedule_exceptions:
                            raise ValueError("El horario ha cambiado en Google Sheets. Recarga antes de editar.")
                        if mode == "default":
                            # Guardar el horario habitual sin copiar bloques ya realizados.
                            schedule_base = new_slots
                            schedule_exceptions.pop(chosen_day.isoformat(), None)
                        elif mode == "reset":
                            schedule_exceptions.pop(chosen_day.isoformat(), None)
                        else:
                            schedule_exceptions[chosen_day.isoformat()] = new_slots
                        if icloud_enabled:
                            if cloud_error is not None or cloud_signature is None:
                                raise ValueError("No hay conexión válida con iCloud")
                            cloud_client, cloud_cal = icloud_calendar()
                            try:
                                latest_cloud = icloud_events(chosen_day, cloud_cal)
                                if icloud_fingerprint(latest_cloud) != cloud_signature:
                                    raise ValueError("Los eventos de iCloud cambiaron mientras editabas. Recarga antes de guardar.")
                                save_icloud_slots(cloud_cal, chosen_day, latest_cloud, new_slots)
                            finally:
                                cloud_client.close()
                        # Se escribe Sheets después de iCloud. Si falla Sheets, se
                        # informa del guardado parcial y el siguiente refresco lee iCloud.
                        try:
                            write_schedule(ws, schedule_base, schedule_exceptions)
                        except Exception as exc:
                            if icloud_enabled:
                                raise RuntimeError(f"iCloud se actualizó, pero Google Sheets falló: {exc}") from exc
                            raise
                        st.session_state[event_key] = signature
                        st.toast("Horario guardado en iCloud y Google Sheets" if icloud_enabled else "Horario guardado en Google Sheets")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"No se pudo guardar el horario: {exc}")
            st.caption("«Guardar como habitual» prepara el horario para futuros días laborables; «Restablecer día» recupera el horario habitual. Ambos se aplican solo al pulsar «Guardar cambios».")
            if chosen_day <= DEADLINE:
                plan = recovery_plan(records, today, DEADLINE, expected_hist - worked_hist)
                if plan is not None:
                    _, needed, _, _, _ = plan
                    st.caption(f"Para llegar al 15/12/2026, las horas pendientes estimadas desde hoy son {fmt(needed)}. El horario es orientativo; registra las horas reales por separado.")


