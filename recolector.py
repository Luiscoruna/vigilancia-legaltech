import os
import re
import csv
import json
import time
import hashlib
import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from datetime import datetime
from urllib.parse import urljoin, urlparse
import markdown
import urllib3

# Silenciar advertencias al forzar la lectura de webs con certificados inválidos (ej. Aranzadi)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ESTADO_DIR = 'estado'

# Pistas que indican que un enlace lleva a una noticia/novedad (para priorizarlo)
PISTAS_NOTICIA = (
    'noticia', 'noticias', 'actualidad', 'blog', 'news', 'press', 'prensa',
    'sala-de-prensa', 'lanzamiento', 'novedad', 'novedades', 'producto',
    'productos', 'evento', 'webinar', 'comunicado', 'articulo', 'post'
)

EXTENSIONES_IGNORAR = ('.pdf', '.jpg', '.jpeg', '.png', '.gif', '.svg',
                       '.webp', '.zip', '.css', '.js', '.ico', '.mp4')


# ---------------------------------------------------------------------------
# Utilidades de extracción
# ---------------------------------------------------------------------------
def enlace_es_util(href, texto_ancla):
    if not href:
        return False
    h = href.strip().lower()
    if h.startswith(('#', 'mailto:', 'tel:', 'javascript:', 'data:')):
        return False
    if h.endswith(EXTENSIONES_IGNORAR):
        return False
    if len((texto_ancla or '').strip()) < 4:
        return False
    return True


def extraer_enlaces(soup, url_base, max_enlaces=20):
    """Saca los enlaces internos (mismo dominio) en absoluto, priorizando noticias."""
    dominio_base = urlparse(url_base).netloc.replace('www.', '')
    candidatos = []
    vistos = set()

    for a in soup.find_all('a', href=True):
        href = a['href']
        texto = ' '.join(a.stripped_strings)
        if not enlace_es_util(href, texto):
            continue
        url_abs = urljoin(url_base, href)
        dominio = urlparse(url_abs).netloc.replace('www.', '')
        if dominio_base not in dominio:
            continue
        url_limpia = url_abs.split('#')[0].rstrip('/')
        if not url_limpia or url_limpia in vistos or url_limpia == url_base.rstrip('/'):
            continue
        vistos.add(url_limpia)
        puntuacion = sum(1 for p in PISTAS_NOTICIA if p in url_limpia.lower())
        candidatos.append((puntuacion, url_limpia, texto[:80]))

    candidatos.sort(key=lambda c: c[0], reverse=True)
    return [(u, t) for _, u, t in candidatos[:max_enlaces]]


def resolver_redireccion(url):
    """Sigue la redirección interna de Google hasta el dominio real."""
    try:
        r = requests.get(url, allow_redirects=True, timeout=8,
                         headers={'User-Agent': 'Mozilla/5.0'})
        return r.url or url
    except Exception:
        return url


# ---------------------------------------------------------------------------
# Utilidades de ESTADO (memoria entre ejecuciones)
# ---------------------------------------------------------------------------
def nombre_estado(id_fuente):
    seguro = re.sub(r'[^A-Za-z0-9_-]', '_', id_fuente) or 'fuente'
    return os.path.join(ESTADO_DIR, f"{seguro}.json")


def cargar_estado(id_fuente):
    ruta = nombre_estado(id_fuente)
    if os.path.exists(ruta):
        try:
            with open(ruta, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None
    return None


def guardar_estado(id_fuente, texto_hash, enlaces_conocidos):
    os.makedirs(ESTADO_DIR, exist_ok=True)
    with open(nombre_estado(id_fuente), 'w', encoding='utf-8') as f:
        json.dump({
            'texto_hash': texto_hash,
            'enlaces_conocidos': sorted(enlaces_conocidos),
            'ultima_actualizacion': datetime.now().isoformat(timespec='seconds'),
        }, f, ensure_ascii=False, indent=2)


def hash_texto(texto):
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()


# ¿Es la primera vez que se ejecuta?
os.makedirs(ESTADO_DIR, exist_ok=True)
es_primera_ejecucion = not any(f.endswith('.json') for f in os.listdir(ESTADO_DIR))
if es_primera_ejecucion:
    print("ℹ️ Primera ejecución: se guardará la línea base. No se reportarán novedades hoy.")

# ---------------------------------------------------------------------------
# 1. Configurar la API de Gemini
# ---------------------------------------------------------------------------
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise ValueError("No se encontró la API Key de Gemini en los secretos de GitHub.")
client = genai.Client(api_key=api_key)

# ---------------------------------------------------------------------------
# 2. Rastrear fuentes y DETECTAR CAMBIOS contra el estado anterior
# ---------------------------------------------------------------------------
print("Iniciando rastreo de fuentes...")
bloques_novedades = []
fuentes_procesadas = 0
fuentes_con_cambios = 0
fuentes_con_error = []

with open('fuentes.csv', mode='r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        id_fuente = row.get('id', '')
        tipo = row.get('tipo_de_recurso', '')
        query = row.get('query', '')
        if tipo != 'dominio_web' or not query:
            continue

        url = query if query.startswith('http') else f"https://{query}"
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            response = requests.get(url, headers=headers, timeout=12, verify=False)
            if response.status_code != 200:
                fuentes_con_error.append(f"{id_fuente} ({url}): HTTP {response.status_code}")
                print(f"⚠️ {id_fuente}: HTTP {response.status_code}")
                time.sleep(0.5)
                continue

            soup = BeautifulSoup(response.text, 'html.parser')
            texto_limpio = ' '.join(soup.stripped_strings)[:1800]
            enlaces = extraer_enlaces(soup, url)
            urls_actuales = {u for u, _ in enlaces}
            h_actual = hash_texto(texto_limpio)
            fuentes_procesadas += 1

            # --- Comparar contra el estado anterior ---
            estado_prev = cargar_estado(id_fuente)
            if estado_prev is None:
                enlaces_nuevos = set()
                texto_cambiado = False
                conocidos = set()
            else:
                conocidos = set(estado_prev.get('enlaces_conocidos', []))
                enlaces_nuevos = urls_actuales - conocidos
                texto_cambiado = estado_prev.get('texto_hash') != h_actual

            guardar_estado(id_fuente, h_actual, conocidos | urls_actuales)

            hay_novedad = bool(enlaces_nuevos) or (texto_cambiado and estado_prev is not None)
            if hay_novedad and not es_primera_ejecucion:
                fuentes_con_cambios += 1
                bloque = f"--- WEB: {id_fuente} (HOME: {url}) ---\n"
                if enlaces_nuevos:
                    bloque += "ENLACES NUEVOS (no estaban en la ultima ejecucion; usalos para enlazar):\n"
                    mapa = {u: t for u, t in enlaces}
                    for u in sorted(enlaces_nuevos):
                        bloque += f"- {u} | \"{mapa.get(u, '')}\"\n"
                if texto_cambiado:
                    bloque += "CAMBIO DETECTADO EN EL TEXTO DE LA HOME: si\n"
                bloque += f"TEXTO ACTUAL (extracto):\n{texto_limpio}\n"
                bloques_novedades.append(bloque)
                print(f"🆕 {id_fuente}: {len(enlaces_nuevos)} enlace(s) nuevo(s), texto cambiado={texto_cambiado}")
            else:
                print(f"✅ {id_fuente} leida. Sin novedades.")

        except Exception as e:
            fuentes_con_error.append(f"{id_fuente} ({url}): {type(e).__name__}")
            print(f"❌ Error al leer {id_fuente}: {e}")

        time.sleep(0.5)

texto_consolidado = "\n".join(bloques_novedades)
bloque_errores = "\n".join(f"- {e}" for e in fuentes_con_error) or "Ninguno."

# ---------------------------------------------------------------------------
# 3. Generar el boletin con Gemini (Escaparates = novedades; Ecosistema = busqueda)
# ---------------------------------------------------------------------------
print("Analizando datos con Gemini y buscando en internet...")
fecha_hoy = datetime.now().strftime("%d de %B de %Y")
hora_actual = datetime.now().strftime("%H:%M:%S")

if es_primera_ejecucion:
    nota_escaparates = ("Hoy es la PRIMERA ejecucion: se ha guardado la linea base de todas las "
                        "webs. En la seccion Escaparates escribe unicamente: 'Linea base "
                        "registrada. A partir de la proxima ejecucion se detectaran cambios reales.'")
elif not bloques_novedades:
    nota_escaparates = ("No se han detectado enlaces nuevos ni cambios en las webs vigiladas. "
                        "En la seccion Escaparates escribe unicamente: 'Sin cambios detectados en "
                        "las webs vigiladas desde la ultima ejecucion.'")
else:
    nota_escaparates = ("Construye la seccion Escaparates EXCLUSIVAMENTE con las novedades listadas "
                        "abajo. Cada novedad DEBE enlazar al ENLACE NUEVO correspondiente en Markdown.")

prompt = f"""
Actua como un analista de legaltech en Espana y experto en inteligencia artificial juridica.
Redacta el boletin diario de inteligencia competitiva para la direccion de Producto.
Hoy es {fecha_hoy}.

INSTRUCCION PARA LA SECCION ESCAPARATES:
{nota_escaparates}

NOVEDADES DETECTADAS DESDE LA ULTIMA EJECUCION:
{texto_consolidado or "(ninguna)"}

WEBS QUE FALLARON O FUERON BLOQUEADAS HOY:
{bloque_errores}

INSTRUCCIONES GENERALES:
1. ESCAPARATES: sigue exactamente la instruccion de arriba.
2. ECOSISTEMA (BUSQUEDA EXTERNA): usa tu herramienta de busqueda para noticias reales de HOY
   ({fecha_hoy}) sobre IA Jurídica y Legaltech (Harvey, Wolters Kluwer, LexisNexis, Legora, etc.).
3. OBSERVACIONES TECNICAS: menciona explicitamente las webs de la lista de fallos.
4. Espanol, tono analitico, corporativo y directo.

Estructura en Markdown con estos encabezados exactos:
- ## Novedades en los Escaparates (Cambios detectados en sus webs)
- ## Ecosistema y Eventos de Hoy (Noticias y webinars detectados en internet)
- ## Radar de Posicionamiento estratégico
- ## Observaciones Técnicas
"""

respuesta = client.models.generate_content(
    model='gemini-2.5-flash',
    contents=prompt,
    config=types.GenerateContentConfig(tools=[{"google_search": {}}])
)

texto_ia = respuesta.text

# --- Inyección de citas inline precisas basadas en bytes del Buscador ---
seccion_fuentes_html = ""
try:
    candidato = respuesta.candidates[0] if respuesta.candidates else None
    metadata = getattr(candidato, "grounding_metadata", None) if candidato else None
    
    if metadata and metadata.grounding_chunks:
        chunks = metadata.grounding_chunks
        supports = metadata.grounding_supports or []
        print(f"Buscador: {len(chunks)} fuentes de internet indexadas.")
        
        # Procesamos de atrás hacia adelante en formato binario (bytes) para respetar offsets UTF-8 exactos
        texto_bytes = texto_ia.encode('utf-8')
        supports_ordenados = sorted(
            [s for s in supports if s.segment and s.segment.end_index is not None],
            key=lambda s: s.segment.end_index, reverse=True
        )
        for s in supports_ordenados:
            end = s.segment.end_index
            indices = s.grounding_chunk_indices or []
            marcas = ''.join(f'[{i + 1}]' for i in indices)
            if marcas:
                texto_bytes = texto_bytes[:end] + marcas.encode('utf-8') + texto_bytes[end:]
        texto_ia = texto_bytes.decode('utf-8', errors='ignore')

        enlaces_detectados = []
        for chunk in chunks:
            if chunk.web and chunk.web.uri:
                url_real = resolver_redireccion(chunk.web.uri)
                titulo = chunk.web.title or urlparse(url_real).netloc or "Noticia sectorial"
                enlaces_detectados.append({'titulo': titulo, 'url': url_real})

        if enlaces_detectados:
            seccion_fuentes_html = "<br><hr><h2>🔗 Fuentes de Internet consultadas hoy por el Radar</h2><ol>"
            for link in enlaces_detectados:
                seccion_fuentes_html += f'<li><a href="{link["url"]}" target="_blank" rel="noopener">{link["titulo"]}</a></li>'
            seccion_fuentes_html += "</ol>"
    else:
        # El valioso aviso técnico sugerido para el log de Actions
        print("Nota tecnica: el buscador no devolvio fuentes (grounding_chunks vacio o sin metadata).")
except Exception as e:
    print(f"⚠️ Nota técnica en el procesado de citas inline: {e}")

html_generado_por_ia = markdown.markdown(texto_ia)

# ---------------------------------------------------------------------------
# 4. Construir el dashboard final con control de tiempo activo
# ---------------------------------------------------------------------------
print("Construyendo el panel web...")
os.makedirs('docs', exist_ok=True)
etiqueta_cambios = f"{fuentes_con_cambios} con novedades · {fuentes_procesadas} analizadas"

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
ul, ol {{ padding-left: 20px; }}
li {{ margin-bottom: 8px; }}
</style>
</head>
<body>
<div class="cabecera">
<div>
<h1>Vigilancia Legaltech</h1>
<p class="metadatos">Última actualización: {fecha_hoy} a las {hora_actual} (Hora servidor)</p>
</div>
<div class="marcador">
{etiqueta_cambios}
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