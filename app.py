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
TIMELINE_HTML = '<!doctype html><html lang="es"><head><meta charset="utf-8"><style>\n:root{color-scheme:light dark}*{box-sizing:border-box}body{margin:0;padding:3px 2px 7px;font:14px system-ui,-apple-system,Segoe UI,sans-serif;color:var(--text-color,#262730);background:transparent}.panel{border:1px solid var(--secondary-background-color,#e4e8ee);border-radius:13px;padding:14px;background:var(--background-color,transparent)}.heading{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:16px}.heading strong{font-size:14px}.total{font-size:22px;font-weight:750;letter-spacing:-.6px;font-variant-numeric:tabular-nums}.sub{font-size:11px;color:var(--muted,#7b8794)}.axis{display:flex;justify-content:space-between;font-size:10px;color:var(--muted,#7b8794);margin:0 1px 7px}.track{height:39px;position:relative;border-radius:9px;background:var(--secondary-background-color,#e8edf4);touch-action:none;overflow:visible}.slot{position:absolute;top:5px;height:29px;background:var(--primary-color,#2563eb);border-radius:6px;cursor:grab;touch-action:none;min-width:4px;box-shadow:0 2px 5px #0002}.slot.active{outline:2px solid var(--text-color,#263445);outline-offset:2px}.handle{position:absolute;top:-4px;width:9px;height:37px;border-radius:5px;background:var(--text-color,#1e40af);cursor:ew-resize;touch-action:none;opacity:.78}.handle.left{left:-4px}.handle.right{right:-4px}.slotlabel{pointer-events:none;text-align:center;line-height:29px;color:white;font-size:10px;white-space:nowrap;overflow:hidden;padding:0 8px}.items{display:flex;gap:6px;flex-wrap:wrap;margin:13px 0 10px;min-height:27px}button{cursor:pointer;border:1px solid var(--secondary-background-color,#d6dce5);background:var(--secondary-background-color,#f2f5f9);color:var(--text-color,#263445);border-radius:8px;padding:7px 11px;font:12px system-ui,sans-serif}button:disabled{opacity:.45;cursor:default}.chip{font-size:11px;padding:5px 9px}.chip.active{border-color:var(--primary-color,#2563eb);color:var(--primary-color,#2563eb);font-weight:700}.actions{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.spacer{flex:1}.save{background:var(--primary-color,#2563eb);color:white;border-color:var(--primary-color,#2563eb);font-weight:650}.save:disabled{opacity:.5}.error{font-size:12px;color:#dc2626;min-height:16px;margin-top:8px}.status{font-size:11px;color:var(--muted,#7b8794);margin-top:9px}.status.dirty{color:var(--primary-color,#2563eb)}\n</style></head><body><div class="panel"><div class="heading"><div><strong>Franjas del día</strong><div class="sub">Arrastra el bloque o sus extremos · pasos de 15 min</div></div><div style="text-align:right"><div id="total" class="total">0 h 00 min</div><div class="sub">Total planificado</div></div></div><div class="axis"><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span></div><div id="track" class="track"></div><div id="items" class="items"></div><div class="actions"><button id="add">＋ Añadir</button><button id="remove">− Eliminar</button><button id="reset">Restablecer día</button><button id="default">Guardar como habitual</button><div class="spacer"></div><button id="save" class="save">Guardar cambios</button></div><div id="status" class="status">Sin cambios pendientes</div><div id="error" class="error"></div></div>\n<script>\nlet slots=[],active=-1,readonly=false,day=\'\',initialized=false,drag=null,base=[],dirty=false,mode=\'day\',saved=[];const $=id=>document.getElementById(id);const fmt=n=>String(Math.floor(n/4)).padStart(2,\'0\')+\':\'+String(n%4*15).padStart(2,\'0\');const total=()=>slots.reduce((a,s)=>a+s[1]-s[0],0);const valid=arr=>Array.isArray(arr)&&arr.length<=20&&arr.every(s=>Array.isArray(s)&&s.length===2&&Number.isInteger(s[0])&&Number.isInteger(s[1])&&s[0]>=0&&s[1]<=96&&s[0]<s[1])&&arr.every((s,i)=>arr.every((t,j)=>i===j||s[1]<=t[0]||t[1]<=s[0]));const clone=x=>x.map(s=>s.slice());\nfunction status(){ $(\'status\').textContent=dirty?\'Cambios sin guardar · pulsa «Guardar cambios» para aplicarlos\':\'Sin cambios pendientes\';$(\'status\').classList.toggle(\'dirty\',dirty);$(\'save\').disabled=readonly||!dirty;}\nfunction change(){dirty=true;mode=\'day\';status();$(\'error\').textContent=\'\'}\nfunction emit(){window.parent.postMessage({isStreamlitMessage:true,type:\'streamlit:setComponentValue\',value:{day,slots:clone(slots),mode}},\'*\')}\nfunction draw(){slots.sort((a,b)=>a[0]-b[0]);$(\'track\').innerHTML=\'\';$(\'items\').innerHTML=\'\';slots.forEach((s,i)=>{let el=document.createElement(\'div\');el.className=\'slot\'+(active===i?\' active\':\'\');el.style.left=s[0]/96*100+\'%\';el.style.width=(s[1]-s[0])/96*100+\'%\';el.innerHTML=\'<div class="handle left" data-edge="start"></div><div class="slotlabel">\'+fmt(s[0])+\'–\'+fmt(s[1])+\'</div><div class="handle right" data-edge="end"></div>\';el.addEventListener(\'pointerdown\',e=>{if(readonly)return;active=i;drag={i,edge:e.target.dataset.edge||\'move\',x:e.clientX,orig:s.slice(),pointer:e.pointerId};el.setPointerCapture(e.pointerId);drawActive();e.preventDefault()});el.addEventListener(\'pointermove\',e=>{if(!drag||drag.i!==i||drag.pointer!==e.pointerId)return;let width=$(\'track\').getBoundingClientRect().width;let delta=Math.round((e.clientX-drag.x)/width*96);let a=drag.orig.slice();if(drag.edge===\'start\')a[0]=Math.max(0,Math.min(a[1]-1,a[0]+delta));else if(drag.edge===\'end\')a[1]=Math.min(96,Math.max(a[0]+1,a[1]+delta));else{let len=a[1]-a[0];a[0]=Math.max(0,Math.min(96-len,a[0]+delta));a[1]=a[0]+len}let next=clone(slots);next[i]=a;if(valid(next)){slots[i]=a;el.style.left=a[0]/96*100+\'%\';el.style.width=(a[1]-a[0])/96*100+\'%\';el.querySelector(\'.slotlabel\').textContent=fmt(a[0])+\'–\'+fmt(a[1]);updateTotal();change()}});el.addEventListener(\'pointerup\',e=>{if(drag&&drag.i===i){drag=null;draw()}});el.addEventListener(\'pointercancel\',()=>{drag=null;draw()});$(\'track\').appendChild(el);let chip=document.createElement(\'button\');chip.className=\'chip\'+(active===i?\' active\':\'\');chip.textContent=fmt(s[0])+\'–\'+fmt(s[1]);chip.onclick=()=>{active=i;draw()};$(\'items\').appendChild(chip)});updateTotal();$(\'remove\').disabled=readonly||active<0||active>=slots.length;$(\'add\').disabled=readonly;$(\'reset\').disabled=readonly;$(\'default\').disabled=readonly;status()}\nfunction updateTotal(){let n=total()*15;$(\'total\').textContent=Math.floor(n/60)+\' h \'+String(n%60).padStart(2,\'0\')+\' min\'}\nfunction drawActive(){Array.from($(\'track\').children).forEach((el,i)=>el.classList.toggle(\'active\',i===active));Array.from($(\'items\').children).forEach((el,i)=>el.classList.toggle(\'active\',i===active));$(\'remove\').disabled=readonly||active<0}\n$(\'add\').onclick=()=>{for(let a=32;a<=92;a++){let candidate=[a,a+4];if(valid([...slots,candidate])){slots.push(candidate);active=slots.length-1;change();draw();return}}$(\'error\').textContent=\'No queda espacio libre para añadir una franja de una hora.\'};$(\'remove\').onclick=()=>{if(active<0)return;slots.splice(active,1);active=slots.length?0:-1;change();draw()};$(\'reset\').onclick=()=>{slots=clone(base);active=slots.length?0:-1;mode=\'reset\';dirty=true;draw();$(\'status\').textContent=\'Se restablecerá al guardar\';};$(\'default\').onclick=()=>{if(readonly)return;mode=\'default\';dirty=true;status();$(\'status\').textContent=\'Se guardará como horario habitual al pulsar Guardar cambios\';};$(\'save\').onclick=()=>{if(!dirty||readonly)return;if(!valid(slots)){$(\'error\').textContent=\'Hay franjas solapadas o no válidas\';return}emit();$(\'save\').disabled=true;$(\'status\').textContent=\'Guardando en Google Sheets…\'};\nwindow.addEventListener(\'message\',e=>{if(e.data.type!==\'streamlit:render\')return;let args=e.data.args||{};let theme=e.data.theme||args.theme||{};for(let [key,css] of [[\'primaryColor\',\'--primary-color\'],[\'backgroundColor\',\'--background-color\'],[\'secondaryBackgroundColor\',\'--secondary-background-color\'],[\'textColor\',\'--text-color\']]){if(theme[key])document.documentElement.style.setProperty(css,theme[key])}if(!initialized||args.day!==day||args.revision!==window.revision){day=args.day;window.revision=args.revision;slots=clone(args.slots||[]);saved=clone(slots);base=clone(args.base||[]);readonly=!!args.readonly;maxQuarters=args.max_quarters||96;active=slots.length?0:-1;dirty=false;mode=\'day\';initialized=true;draw()}});window.parent.postMessage({isStreamlitMessage:true,type:\'streamlit:componentReady\',apiVersion:1},\'*\');window.parent.postMessage({isStreamlitMessage:true,type:\'streamlit:setFrameHeight\',height:245},\'*\');\n</script></body></html>\n'

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
