import requests
from bs4 import BeautifulSoup

def obtener_tasas_bcv():
    url = "https://www.bcv.org.ve/"
    
    # Es vital usar un User-Agent para que el servidor no bloquee la petición
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    try:
        # verify=False se usa a veces si el certificado del BCV da problemas, 
        # pero lo ideal es dejarlo en True por seguridad.
        response = requests.get(url, headers=headers, verify=False)
        response.raise_for_status() # Verifica si la página cargó bien

        soup = BeautifulSoup(response.text, 'html.parser')

        # Diccionario para guardar los resultados
        tasas = {}

        # Mapeo de los IDs de la página del BCV
        monedas = {
            'dolar': 'dolar',
            'euro': 'euro',
            'yuan': 'yuan',
            'lira': 'try',
            'rublo': 'rub'
        }

        for moneda, id_html in monedas.items():
            # El BCV usa IDs específicos para cada moneda
            elemento = soup.find('div', id=id_html)
            if elemento:
                # Buscamos el valor numérico dentro del div
                valor = elemento.find('strong').text.strip()
                # Reemplazamos coma por punto para poder convertir a float si hace falta
                tasas[moneda] = valor.replace(',', '.')

        return tasas

    except Exception as e:
        return f"Error al conectar con el BCV: {e}"

if __name__ == "__main__":
    datos = obtener_tasas_bcv()
    
    if isinstance(datos, dict):
        print("--- Tasas Oficiales BCV ---")
        for m, v in datos.items():
            print(f"{m.capitalize()}: {v} Bs.")
    else:
        print(datos)