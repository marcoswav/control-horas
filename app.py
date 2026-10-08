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

# ------------------ CONEXIÓN CON GOOGLE SHEETS (OPTIMIZADA CON CACHÉ) ------------------
@st.cache_resource
def conectar
