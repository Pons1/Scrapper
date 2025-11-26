#!/usr/bin/env python3
import os
import csv
import re
import time
import logging
import mimetypes
import smtplib
import requests
import urllib3
from bs4 import BeautifulSoup as bs
from datetime import datetime

# Deshabilitar advertencias de SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.mime.application import MIMEApplication


# ---------------------- CONFIGURACIÓN DE EMAIL ----------------------
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "perfuscrapper@gmail.com")     # ej: tu correo completo
SMTP_PASS = os.environ.get("SMTP_PASS", "kvwo vhhq navc xbwh ")     # ej: app password
EMAIL_FROM = os.environ.get("EMAIL_FROM", SMTP_USER)
EMAIL_TO   = os.environ.get("EMAIL_TO", "adrianpons21@gmail.com")     # destino de notificación


# ---------------------- LOGGING ----------------------
os.makedirs("Logs", exist_ok=True)
LOG_FILE = "Logs/scrapper.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()]
)


# ---------------------- FUNCIONES ----------------------
def extraer_importe_y_divisa(precio_str):
    """Extrae importe y divisa del texto del precio"""
    try:
        precio_str = precio_str.strip().replace("\xa0", " ")
        m = re.search(r"([\d\.,]+)\s*([^\d\s]+)", precio_str)
        if not m:
            return None, None
        return float(m.group(1).replace(",", ".")), m.group(2)
    except Exception as e:
        logging.warning(f"No se pudo extraer precio '{precio_str}': {e}")
        return None, None


def parsear_productos(html, categoria):
    """Convierte el HTML en una lista de productos"""
    datos = []
    soup = bs(html, "lxml")
    listado = soup.find("div", class_="products product_list row grid clear_list_18 clear_list_align_0 clear_list_proportion_0")
    if not listado:
        return datos
    for product in listado.find_all("div", class_="product_list_item"):
        try:
            name = product.find("h3", class_="s_title_block flex_child").get_text(strip=True)
            precio_raw = product.find("span", class_="price").get_text(strip=True)
            importe, divisa = extraer_importe_y_divisa(precio_raw)
            enlace = product.find("a", class_="tm_gallery_item_box")
            url_prod = enlace["href"] if enlace and enlace.has_attr("href") else "Sin enlace"
            img_tag = enlace.find("img") if enlace else None
            url_img = (img_tag.get("data-src") or img_tag.get("src")) if img_tag else "Sin imagen"
            datos.append([categoria, name, importe, divisa, url_prod, url_img])
        except Exception as e:
            logging.warning(f"Error procesando producto ({categoria}): {e}")
    return datos


def scrapear_categoria_por_requests(url_inicio, categoria):
    """Scrapea una categoría siguiendo paginación con requests/BeautifulSoup.

    Intentará seguir un enlace 'rel=next' o enlaces habituales de paginación hasta
    agotar las páginas.
    """
    logging.info(f"Scraping por requests de la categoría {categoria}: {url_inicio}")
    datos = []
    url = url_inicio
    headers = {"User-Agent": "Mozilla/5.0"}
    max_pages = 50
    paginas = 0

    while url and paginas < max_pages:
        paginas += 1
        logging.info(f"Pidiendo página {paginas}: {url}")
        r = requests.get(url, headers=headers, timeout=15, verify=False)
        if r.status_code != 200:
            logging.error(f"Error {r.status_code} al pedir {url}")
            break
        html = r.content
        datos.extend(parsear_productos(html, categoria))
        soup = bs(html, "lxml")

        # 1) Intentar link rel=next
        next_link = None
        link_rel = soup.find("link", rel="next")
        if link_rel and link_rel.has_attr("href"):
            next_link = link_rel["href"]

        # 2) Buscar un enlace con texto "Siguiente"/"Next"/">" o clase 'next'
        if not next_link:
            a_next = soup.find("a", string=lambda s: s and ("Siguiente" in s or "Next" in s or s.strip() == ">"))
            if a_next and a_next.has_attr("href"):
                next_link = a_next["href"]
        if not next_link:
            a_next = soup.find("a", class_=lambda c: c and "next" in c)
            if a_next and a_next.has_attr("href"):
                next_link = a_next["href"]

        if not next_link:
            logging.info("No se encontró siguiente página (requests). Termino.")
            break

        # Normalizar URL relativa
        if next_link.startswith("/"):
            from urllib.parse import urljoin

            url = urljoin(url, next_link)
        else:
            url = next_link
        time.sleep(1)

    logging.info(f"Scraping por requests completado en {paginas} páginas. Total productos: {len(datos)}")
    return datos


def scrapear_por_paginacion_numerica(url_inicio, categoria, max_pages=20):
    """Scrapea una categoría navegando por ?page=N usando requests.

    Construye las URLs ajustando el parámetro 'page' y itera hasta que no haya productos nuevos.
    """
    logging.info(f"Scraping por paginación numérica de {categoria}: {url_inicio}")
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

    datos = []
    headers = {"User-Agent": "Mozilla/5.0"}

    parsed = urlparse(url_inicio)
    qs = parse_qs(parsed.query)

    # Empezar en la página 1 si no hay page en la URL
    page = int(qs.get("page", [1])[0])

    for p in range(page, page + max_pages):
        qs_copy = dict(qs)
        qs_copy["page"] = [str(p)]
        new_query = urlencode(qs_copy, doseq=True)
        url_parts = (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
        url_p = urlunparse(url_parts)

        logging.info(f"Pidiendo página {p}: {url_p}")
        try:
            r = requests.get(url_p, headers=headers, timeout=15, verify=False)
        except Exception as e:
            logging.error(f"Error al pedir {url_p}: {e}")
            break
        if r.status_code != 200:
            logging.info(f"Respuesta {r.status_code} en {url_p}. Termino paginación.")
            break

        page_datos = parsear_productos(r.content, categoria)
        if not page_datos:
            logging.info(f"No se encontraron productos en la página {p}. Fin de paginación.")
            break

        datos.extend(page_datos)
        # pequeña espera para no sobrecargar
        time.sleep(0.8)

    logging.info(f"Paginación numérica completada. Total productos: {len(datos)}")
    return datos


def scrapear_mujer_por_paginacion():
    """Scrapea la categoría Mujer usando paginación numérica (?page=N)."""
    url = "https://www.perfumarte.com/tienda/perfumes/perfume-de-mujer/"
    # La categoría de mujer tiene 9 páginas según el usuario
    return scrapear_por_paginacion_numerica(url, "Mujer", max_pages=9)


def enviar_email(asunto, mensaje, archivo_csv=None, archivo_log=None):
    """Envía un correo con los archivos adjuntos (simplificado).

    Adjunta los archivos CSV/log si existen usando MIMEApplication, que maneja
    bien nombres y contenido binario. Usa sendmail con la lista de destinatarios.
    """
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_FROM
        destinatarios = [d.strip() for d in EMAIL_TO.split(",") if d.strip()]
        msg["To"] = ", ".join(destinatarios)
        msg["Subject"] = asunto
        msg.attach(MIMEText(mensaje, "plain"))

        archivos = [archivo_csv, archivo_log]
        for archivo in archivos:
            if not archivo:
                continue
            if not os.path.exists(archivo):
                logging.warning(f"Archivo no encontrado para adjuntar: {archivo}")
                continue
            try:
                with open(archivo, "rb") as f:
                    part = MIMEApplication(f.read(), Name=os.path.basename(archivo))
                part.add_header("Content-Disposition", "attachment", filename=os.path.basename(archivo))
                msg.attach(part)
                logging.info(f"Adjuntado: {archivo}")
            except Exception as e:
                logging.error(f"No pude adjuntar {archivo}: {e}")

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(EMAIL_FROM, destinatarios, msg.as_string())
        logging.info("Correo enviado correctamente.")
    except Exception as e:
        logging.error(f"No se pudo enviar el correo: {e}")


def guardar_csv(datos):
    """Guarda los datos en CSV"""
    os.makedirs("Resultados", exist_ok=True)
    fecha = datetime.now().strftime("%Y-%m-%d")
    ruta = os.path.join("Resultados", f"{fecha}-perfumarte-Adrian_Pons.csv")
    try:
        with open(ruta, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            # Metadatos (fila 1)
            w.writerow(["Fecha", "Fuente", "Autor"])
            w.writerow([fecha, "Perfumarte", "Adrian Pons"])
            w.writerow([])
            # Encabezado de datos
            w.writerow(["Categoría", "Nombre", "Importe", "Divisa", "URL", "URL_Imagen"])
            w.writerows(datos)
        logging.info(f"CSV creado: {ruta}")
        return ruta
    except Exception as e:
        logging.error(f"Error al guardar CSV: {e}")
        return None


# ---------------------- EJECUCIÓN ----------------------
if __name__ == '__main__':
    try:
        datos_totales = []

        # HOMBRE (usar paginación numérica)
        url_hombre = "https://www.perfumarte.com/tienda/perfumes/perfume-de-hombre/"
        logging.info("Scrapeando perfumes de Hombre (paginación)...")
        datos_totales.extend(scrapear_por_paginacion_numerica(url_hombre, "Hombre"))

        # MUJER (paginación numérica)
        datos_totales.extend(scrapear_mujer_por_paginacion())

        # BODY MIST (paginación numérica)
        url_body = "https://www.perfumarte.com/tienda/perfumes/body-mist/"
        logging.info("Scrapeando Body Mist (paginación)...")
        datos_totales.extend(scrapear_por_paginacion_numerica(url_body, "Body Mist"))

        # CSV + EMAIL
        if datos_totales:
            csv_path = guardar_csv(datos_totales)
            enviar_email(
                "Scraping completado correctamente",
                f"Scraping completado con {len(datos_totales)} productos extraídos.",
                archivo_csv=csv_path,
                archivo_log=LOG_FILE
            )
        else:
            enviar_email("Scraping fallido", "No se encontraron productos.", archivo_log=LOG_FILE)

    except Exception as e:
        logging.critical(f"Error crítico: {e}")
        enviar_email("Scraping fallido", f"Error crítico: {e}", archivo_log=LOG_FILE)
