import requests
from bs4 import BeautifulSoup as bs
from datetime import datetime
import csv

# Cabeceras para simular un navegador real
cabeceras = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.11'
}

# URL a scrapear
url = "https://www.perfumarte.com/tienda/perfumes/perfume-de-hombre/amaderados/"
page = requests.get(url, headers=cabeceras)
ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

if page.status_code != 200:
    print(f"LOG {ahora}: Fallo en el sistema, código de error: {page.status_code}")

else:
    print(f"LOG {ahora}: Scrapping realizado correctamente, resultado:")

    soup = bs(page.content, 'lxml')

    listado = soup.find("div", class_="products product_list row grid clear_list_18 clear_list_align_0 clear_list_proportion_0")
    products = listado.find_all("div", class_="product_list_item")

    # Lista donde guardaremos los productos
    datos = []

    for i, product in enumerate(products, start=1):
        name = product.find("h3", class_="s_title_block flex_child").text.strip()
        precio = product.find("span", class_="price").text.strip()

        print(f"Producto {i}:")
        print("Nombre/Descripción:", name)
        print("Precio:", precio)
        print("—" * 30)

        datos.append([name, precio])

    # Guardar en CSV
    with open("productos.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Nombre", "Precio"])
        writer.writerows(datos)

    print(f"\n✅ Archivo 'productos.csv' creado con {len(datos)} productos.")
