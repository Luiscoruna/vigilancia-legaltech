import os
import csv
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from datetime import datetime
import markdown

# 1. Configurar la API de Gemini
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise ValueError("No se encontró la API Key de Gemini en los secretos de GitHub.")
genai.configure(api_key=api_key)

# 2. Leer el CSV y extraer texto de las webs
print("Iniciando rastreo de fuentes...")
textos_web = []
fuentes_procesadas = 0

with open('fuentes.csv', mode='r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        id_fuente = row.get('id', '')
        tipo = row.get('tipo_de_recurso', '')
        query = row.get('query', '')

        if tipo == 'dominio_web' and query:
            url = f"https://{query}" if not query.startswith('http') else query
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                response = requests.get(url, headers=headers, timeout=10)
                
                soup = BeautifulSoup(response.text, 'html.parser')
                texto_limpio = ' '.join(soup.stripped_strings)[:2000]
                
                textos_web.append(f"--- WEB: {id_fuente} ({url}) ---\n{texto_limpio}\n")
                fuentes_procesadas += 1
                print(f"✅ {id_fuente} leída con éxito.")
            except Exception as e:
                print(f"❌ Error al intentar leer {id_fuente}: {e}")

texto_consolidado = "\n".join(textos_web)

# 3. Mandar el cerebro a trabajar (El Prompt)
print("Analizando datos con Gemini...")
fecha_hoy = datetime.now().strftime("%d de %B de %Y")

prompt = f"""
Actúa como un analista de legaltech especializado en el mercado español e inteligencia artificial aplicada al sector jurídico.
Tu tarea es redactar un boletín diario de inteligencia competitiva para la dirección de Producto.

Hoy es {fecha_hoy}.

A continuación, te proporciono un volcado de textos extraídos HOY DIRECTAMENTE de las páginas principales de la competencia:
{texto_consolidado}

Instrucciones:
1. Analiza el texto y extrae CUALQUIER novedad: lanzamientos, nuevos módulos, webinars (ej. Legora, LawDroid), eventos, artículos corporativos, integraciones menores o cambios de mensaje de marketing.
2. No descartes información por no ser "disruptiva". Todo movimiento es relevante para la monitorización.
3. Si tras analizar TODO el texto realmente no hay nada aprovechable, indica de forma clara y profesional: "El escaneo automático no ha detectado variaciones ni publicaciones destacables en los dominios analizados durante el día de hoy."
4. Escribe en español, con un tono analítico y directo. 

Estructura tu respuesta en Markdown usando estos encabezados (omite los que estén vacíos):
- ## Novedades y Actualizaciones
- ## Eventos y Webinars del Sector
- ## Radar de Posicionamiento (Cambios detectados en sus webs)
"""

model = genai.GenerativeModel('gemini-1.5-flash')
respuesta = model.generate_content(prompt)

html_generado_por_ia = markdown.markdown(respuesta.text)

# 4. Construir la página web final (Dashboard)
print("Construyendo el panel web...")
os.makedirs('docs', exist_ok=True)

plantilla_html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vigilancia Legaltech</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; background-color: #0d1117; color: #c9d1d9; padding: 30px; max-width: 900px; margin: 0 auto; line-height: 1.6; }}
        h1 {{ color: #79c0ff; border-bottom: 1px solid #30363d; padding-bottom: 10px; }}
        h2 {{ color: #7ee787; margin-top: 35px; }}
        h3 {{ color: #d2a8ff; }}
        a {{ color: #58a6ff; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .cabecera {{ display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; }}
        .metadatos {{ font-size: 0.9em; color: #8b949e; }}
        .marcador {{ background-color: rgba(46, 160, 67, 0.15); border: 1px solid rgba(46, 160, 67, 0.4); padding: 8px 16px; border-radius: 20px; color: #3fb950; font-weight: bold; font-size: 0.9em; }}
        .caja-contenido {{ background-color: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 30px; margin-top: 25px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }}
    </style>
</head>
<body>
    <div class="cabecera">
        <div>
            <h1>Vigilancia Legaltech</h1>
            <p class="metadatos">Última actualización: {fecha_hoy}</p>
        </div>
        <div class="marcador">
            Dominios analizados con éxito: {fuentes_procesadas}
        </div>
    </div>
    <div class="caja-contenido">
        {html_generado_por_ia}
    </div>
</body>
</html>"""

with open('docs/index.html', 'w', encoding='utf-8') as f:
    f.write(plantilla_html)

print("¡Proceso terminado! Web generada en docs/index.html")