import os
import csv
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import time
from datetime import datetime, timedelta
import re
import ssl

try:
    from bs4 import BeautifulSoup
    import google.generativeai as genai
except ImportError:
    print("Faltan dependencias. Ejecuta: pip install beautifulsoup4 google-generativeai")
    exit(1)

# Configuración de Gemini
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    
generation_config = {
    "temperature": 0.1,
    "response_mime_type": "application/json",
}

try:
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        generation_config=generation_config,
        system_instruction="""Eres un analista experto y despiadado en Inteligencia Competitiva del sector Legaltech y Compliance. Tu única misión es evaluar noticias corporativas basándote en un Filtro Temático Radical.

REGLAS DE FILTRADO (DESCARTE AUTOMÁTICO):
- Descarta inmediatamente (relevante: false) cualquier noticia que trate sobre sucesos locales, geografía, inmuebles, conventos, o asuntos de la comunidad foral de Navarra (esto ocurre habitualmente por la palabra 'Aranzadi' que es un apellido y una sociedad de ciencias). 
- Solo aprueba (relevante: true) noticias que hablen explícitamente de software para abogados, Legaltech, innovación jurídica, bases de datos legales (como Aranzadi LA LEY, vLex, etc.), IA generativa, lanzamientos tecnológicos (como Allegra o K+), u operaciones corporativas/fusiones empresariales en este sector.

REGLAS DE FORMATO DEL RESUMEN:
1. Cero Meta-Comentarios: Prohibido usar frases como "El modelo ha determinado...", "Hemos analizado...", "Esta noticia trata sobre...", "En resumen...". Ve directo al grano con un tono profesional y periodístico.
2. Prohibido Imprimir URLs: Jamás incluyas enlaces ni URLs dentro del texto del resumen.
3. El resumen debe ser de 2 o 3 líneas máximo, describiendo estrictamente el hecho tecnológico o corporativo concreto.

Debes devolver obligatoriamente un objeto JSON: 
{"relevante": booleano, "resumen": "tu texto aquí respetando las reglas o string vacío si no es relevante"}"""
    )
except Exception as e:
    model = None
    print(f"Error inicializando Gemini: {e}")

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def normalize_url(url):
    if not url: return ""
    url = url.split('#')[0]
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    for param in list(qs.keys()):
        if param.startswith('utm_') or param == 'fbclid':
            del qs[param]
    parsed = parsed._replace(query=urllib.parse.urlencode(qs, doseq=True))
    url = urllib.parse.urlunparse(parsed)
    url = url.replace('www.', '')
    if url.endswith('/'):
        url = url[:-1]
    return url

def fetch_and_clean_text(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req, timeout=10, context=ctx)
        html = response.read()
        soup = BeautifulSoup(html, 'html.parser')
        
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.extract()
            
        text = soup.get_text(separator=' ', strip=True)
        return text[:6000]
    except:
        return ""

def analizar_con_gemini(url, titular):
    if not model:
        return False, "Error: Gemini no está configurado"
        
    texto_limpio = fetch_and_clean_text(url)
    if not texto_limpio or len(texto_limpio) < 50:
        return False, ""
        
    prompt = f"TITULAR: {titular}\n\nTEXTO WEB:\n{texto_limpio}\n\nGenera el JSON."
    
    try:
        response = model.generate_content(prompt)
        data = json.loads(response.text)
        return data.get("relevante", False), data.get("resumen", "")
    except Exception as e:
        return False, ""

def search_rss(query, limit_date):
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote_plus(query) + "&hl=es&gl=ES&ceid=ES:es"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    results = []
    try:
        response = urllib.request.urlopen(req, timeout=15, context=ctx)
        xml_data = response.read()
        root = ET.fromstring(xml_data)
        for item in root.findall('.//item'):
            title = item.find('title').text if item.find('title') is not None else ""
            link = item.find('link').text if item.find('link') is not None else ""
            pub_date_str = item.find('pubDate').text if item.find('pubDate') is not None else ""
            
            item_date = limit_date
            try:
                if pub_date_str:
                    item_date = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %Z")
            except:
                pass
                
            if item_date >= limit_date:
                results.append({'url': link, 'title': title})
                if len(results) >= 3: 
                    break
        return results
    except:
        return []

def scrape_domain(domain):
    if not domain.startswith('http'):
        base_urls = [f"https://www.{domain}", f"https://{domain}"]
    else:
        base_urls = [domain]
        
    results = []
    for base in base_urls:
        endpoints = ['', '/blog', '/noticias', '/news', '/prensa', '/press']
        for ep in endpoints:
            url = base + ep
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                response = urllib.request.urlopen(req, timeout=10, context=ctx)
                html = response.read().decode('utf-8', errors='ignore')
                
                links = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL)
                for href, text in links:
                    text = re.sub(r'<[^>]+>', '', text).strip()
                    if len(text) > 40: 
                        if href.startswith('/'):
                            href = base + href
                        elif not href.startswith('http'):
                            continue
                        results.append({'url': href, 'title': text})
                if results:
                    return results[:5] 
            except:
                continue
    return []

def generar_html(candidatos_finales, fuentes_revisadas, total_fuentes):
    os.makedirs('docs', exist_ok=True)
    html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vigilancia Legaltech & Compliance</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{ --bg-dark: #0f172a; --bg-card: #1e293b; --text-main: #f8fafc; --text-muted: #94a3b8; --accent: #3b82f6; --accent-hover: #60a5fa; --border: #334155; --success: #10b981; }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Inter', sans-serif; background-color: var(--bg-dark); color: var(--text-main); line-height: 1.6; padding: 2rem; min-height: 100vh; }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        header {{ margin-bottom: 3rem; border-bottom: 1px solid var(--border); padding-bottom: 2rem; display: flex; justify-content: space-between; align-items: flex-end; }}
        h1 {{ font-size: 2.5rem; font-weight: 700; background: linear-gradient(to right, #60a5fa, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 0.5rem; }}
        .meta-info {{ color: var(--text-muted); font-size: 0.95rem; }}
        .stats-badge {{ background: rgba(16, 185, 129, 0.1); color: var(--success); padding: 0.5rem 1rem; border-radius: 9999px; font-weight: 500; font-size: 0.9rem; border: 1px solid rgba(16, 185, 129, 0.2); }}
        .news-grid {{ display: grid; gap: 1.5rem; }}
        .news-card {{ background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; transition: transform 0.2s ease, box-shadow 0.2s ease; }}
        .news-card:hover {{ transform: translateY(-2px); box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3); border-color: var(--accent); }}
        .company-tag {{ display: inline-block; background: rgba(59, 130, 246, 0.1); color: var(--accent-hover); font-size: 0.8rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.25rem 0.75rem; border-radius: 6px; margin-bottom: 1rem; }}
        .news-title {{ font-size: 1.25rem; font-weight: 600; margin-bottom: 1rem; color: var(--text-main); }}
        .news-summary {{ color: var(--text-muted); font-size: 0.95rem; margin-bottom: 1.5rem; }}
        .news-link {{ display: inline-flex; align-items: center; color: var(--accent); text-decoration: none; font-weight: 500; font-size: 0.9rem; transition: color 0.2s ease; }}
        .news-link:hover {{ color: var(--accent-hover); }}
        .empty-state {{ text-align: center; padding: 4rem 2rem; color: var(--text-muted); background: var(--bg-card); border-radius: 12px; border: 1px dashed var(--border); }}
        @media (max-width: 768px) {{ header {{ flex-direction: column; align-items: flex-start; gap: 1rem; }} }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1>Vigilancia Legaltech</h1>
                <div class="meta-info">Última actualización: {datetime.now().strftime('%d de %B de %Y, %H:%M')}</div>
            </div>
            <div class="stats-badge">Fuentes analizadas: {fuentes_revisadas} / {total_fuentes}</div>
        </header>
        <div class="news-grid">
"""
    if not candidatos_finales:
        html_content += """
            <div class="empty-state">
                <h3>No hay novedades relevantes hoy</h3>
                <p>El radar inteligente no ha detectado movimientos destacables en el sector.</p>
            </div>
"""
    else:
        for item in candidatos_finales:
            html_content += f"""
            <article class="news-card">
                <div class="company-tag">{item['empresa']}</div>
                <h2 class="news-title">{item['titular']}</h2>
                <p class="news-summary">{item['resumen']}</p>
                <a href="{item['url']}" target="_blank" class="news-link">Leer artículo completo</a>
            </article>
"""
    html_content += "</div></div></body></html>"
    with open('docs/index.html', 'w', encoding='utf-8') as f:
        f.write(html_content)

def main():
    if not GEMINI_API_KEY:
        print("ERROR CRÍTICO: No se ha configurado GEMINI_API_KEY en el entorno.")
        exit(1)
        
    print("Iniciando motor inteligente Gemini...")
    os.makedirs('estado', exist_ok=True)
    try:
        with open('estado/historial.json', 'r', encoding='utf-8-sig') as f:
            historial = json.load(f)
    except:
        historial = {"ultima_ejecucion": None, "items_vistos": []}
        
    items_vistos = set(historial.get('items_vistos', []))
    try:
        limit_date = datetime.fromisoformat(historial.get('ultima_ejecucion'))
    except:
        limit_date = datetime.now() - timedelta(days=7)
    
    fuentes_revisadas = 0
    candidatos_finales = []
    
    with open('fuentes.csv', 'r', encoding='utf-8-sig') as f:
        filas = list(csv.DictReader(f))
        
    for i, row in enumerate(filas):
        recurso = row['id']
        tipo = row['tipo_de_recurso']
        query = row['query']
        print(f"[{i+1}/{len(filas)}] {recurso}...")
        
        resultados_crudos = []
        if tipo == 'dominio_web':
            resultados_crudos = scrape_domain(query)
        elif tipo == 'keyword_busqueda_web':
            resultados_crudos = search_rss(query, limit_date)
            
        fuentes_revisadas += 1
            
        for res in resultados_crudos:
            norm_url = normalize_url(res['url'])
            if f"url:{norm_url}" in items_vistos:
                continue
                
            es_relevante, resumen = analizar_con_gemini(res['url'], res['title'])
            
            if es_relevante and resumen:
                candidatos_finales.append({
                    'empresa': recurso,
                    'titular': res['title'],
                    'url': res['url'],
                    'resumen': resumen
                })
            items_vistos.add(f"url:{norm_url}")
            time.sleep(2) # Respetar límites de Google API
            
    historial['ultima_ejecucion'] = datetime.now().isoformat()
    historial['items_vistos'] = list(items_vistos)
    with open('estado/historial.json', 'w', encoding='utf-8') as f:
        json.dump(historial, f, indent=2, ensure_ascii=False)
        
    generar_html(candidatos_finales, fuentes_revisadas, len(filas))
    print("Dashboard generado en docs/index.html")

if __name__ == '__main__':
    main()
