import os
import csv
import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from datetime import datetime
import markdown
import urllib3

# Silenciar advertencias al forzar la lectura de webs con certificados inválidos (ej. Aranzadi)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. Configurar la API de Gemini
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise ValueError("No se encontró la API Key de Gemini en los secretos de GitHub.")

client = genai.Client(api_key=api_key)

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
                response = requests.get(url, headers=headers, timeout=10, verify=False)
                
                soup = BeautifulSoup(response.text, 'html.parser')
                texto_limpio = ' '.join(soup.stripped_strings)[:2000]
                
                textos_web.append(f"--- WEB: {id_fuente} ({url}) ---\n{texto_limpio}\n")
                fuentes_procesadas += 1
                print(f"✅ {id_fuente} leída con éxito.")
            except Exception as e:
                print(f"❌ Error al intentar leer {id_fuente}: {e}")

texto_consolidado = "\n".join(textos_web)

# 3. Mandar el cerebro a trabajar (Prompt Híbrido + Buscador)
print("Analizando datos con Gemini y buscando en internet...")
fecha_hoy = datetime.now().strftime("%d de %B de %Y")

prompt = f"""
Actúa como un analista de legaltech en España y experto en inteligencia artificial jurídica.
Tu tarea es redactar el boletín diario de inteligencia competitiva para la dirección de Producto.

Hoy es {fecha_hoy}.

FUENTES DIRECTAS (Textos extraídos hoy de sus webs):
{texto_consolidado}

INSTRUCCIONES DE ANÁLISIS:
1. SECCIÓN ESCAPARATES: Extrae lanzamientos o cambios de los textos proporcionados. Cada mención DEBE llevar su enlace extraído de la etiqueta 'WEB:' en formato Markdown (ejemplo: [vLex](https://vlex.es)).
2. SECCIÓN ECOSISTEMA (BÚSQUEDA EXTERNA): Usa tu herramienta de búsqueda en internet para buscar noticias reales de HOY ({fecha_hoy}) sobre IA Jurídica y Legaltech. Analiza los movimientos de Harvey, Wolters Kluwer, LexisNexis, Legora, etc.
3. Si hay webs con errores de acceso, menciónalo al final.
4. Redacta en español, con tono analítico, corporativo y directo.

Estructura tu respuesta en Markdown usando estos encabezados exactos:
- ## Novedades en los Escaparates (Cambios detectados en sus webs)
- ## Ecosistema y Eventos de Hoy (Noticias y webinars detectados en internet)
- ## Radar de Posicionamiento estratégico
- ## Observaciones Técnicas
"""

# Encendemos la herramienta de búsqueda de Google para la IA
respuesta = client.models.generate_content(
    model='gemini-2.5-flash',
    contents=prompt,
    config=types.GenerateContentConfig(
        tools=[{"google_search": {}}]
    )
)

html_generado_por_ia = markdown.markdown(respuesta.text)

# --- TRUCO MAESTRO: Extraer enlaces reales desde la "caja negra" de Google Search ---
seccion_fuentes_html = ""
try:
    metadata = respuesta.candidates[0].grounding_metadata
    if metadata and metadata.grounding_chunks:
        enlaces_detectados = []
        for chunk in metadata.grounding_chunks:
            if chunk.web and chunk.web.uri:
                titulo = chunk.web.title or "Noticia relevante detectada"
                url = chunk.web.uri
                # Evitar meter enlaces duplicados
                if url not in [e['url'] for e in enlaces_detectados]:
                    enlaces_detectados.append({'titulo': titulo, 'url': url})
        
        if enlaces_detectados:
            seccion_fuentes_html = "<br><hr><h2>🔗 Fuentes de Internet consultadas hoy por el Radar</h2><ul>"
            for link in enlaces_detectados:
                seccion_fuentes_html += f'<li><a href="{link["url"]}" target="_blank">{link["titulo"]}</a></li>'
            seccion_fuentes_html += "</ul>"
except Exception as e:
    print(f"Nota técnica: No se pudieron extraer enlaces de los metadatos ({e})")


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
        ul {{ padding-left: 20px; }}
        li {{ margin-bottom: 8px; }}
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
        {seccion_fuentes_html}
    </div>
</body>
</html>"""

with open('docs/index.html', 'w', encoding='utf-8') as f:
    f.write(plantilla_html)

print("¡Proceso terminado! Web generada en docs/index.html")