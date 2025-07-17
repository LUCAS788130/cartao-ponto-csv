import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from PIL import Image
import pytesseract
from pdf2image import convert_from_bytes
import pdfplumber
import io

# Configuração da página
st.set_page_config(page_title="Conversor de Cartão de Ponto OCR ➜ CSV")
st.title("📅 Conversor de Cartão de Ponto (PDF/Imagem) ➜ CSV")

def extrair_texto(file):
    texto = ""
    if file.type == "application/pdf":
