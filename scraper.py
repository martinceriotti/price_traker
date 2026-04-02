import asyncio
import os
import re
import smtplib
import json
from datetime import datetime
from email.mime.text import MIMEText
from playwright.async_api import async_playwright
import gspread
from google.oauth2.service_account import Credentials

# ── Configuración ──────────────────────────────────────────────────────────────
URL = "https://www.samsung.com/ar/tvs/oled-tv/s90f-65-inch-oled-4k-smart-tv-qn65s90fagxzb/"
PRODUCT_NAME = 'Samsung TV OLED S90F 65"'

# Google Sheets
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
SHEET_NAME = "Historial"

# Alerta por email (via Gmail)
EMAIL_FROM = os.environ["EMAIL_FROM"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_TO = os.environ["EMAIL_TO"]
# ──────────────────────────────────────────────────────────────────────────────


def parse_price(raw: str) -> float | None:
    """Limpia texto de precio argentino.
    Maneja ambos formatos:
      - Puntos como miles: $1.299.999 o $4.499.999
      - Comas como miles:  $4,499,999.00 (formato API Samsung)
    """
    if not raw:
        return None

    # Tomar solo la primera línea (evitar "$ 4,499,999.00\nComprar")
    cleaned = raw.split("\n")[0].strip()
    cleaned = cleaned.replace("$", "").strip()

    if not cleaned or not any(c.isdigit() for c in cleaned):
        return None

    # Detectar formato: si tiene comas y punto decimal → formato inglés (4,499,999.00)
    # Si tiene solo puntos → formato AR (4.499.999)
    if "," in cleaned and "." in cleaned:
        # Formato inglés: comas son miles, punto es decimal
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned and "." not in cleaned:
        # Solo comas → son separadores de miles (4,499,999)
        cleaned = cleaned.replace(",", "")
    else:
        # Solo puntos o nada → formato AR: puntos son miles (4.499.999)
        cleaned = cleaned.replace(".", "")

    # Eliminar cualquier caracter no numérico restante (excepto punto decimal)
    cleaned = re.sub(r"[^\d.]", "", cleaned)

    try:
        val = float(cleaned)
        if 100_000 <= val <= 50_000_000:
            return val
        print(f"⚠️  Precio fuera de rango esperado: {val}")
        return None
    except ValueError:
        print(f"❌ No se pudo convertir '{raw}' a número.")
        return None


async def try_extract_price_from_page(page) -> float | None:
    """Intenta extraer el precio del DOM usando múltiples estrategias."""

    # Estrategia 1: Selectores CSS comunes de Samsung AR
    selectors = [
        # Selectores específicos de Samsung AR (2024-2025)
        "[class*='PriceMain'] [class*='price']",
        "[class*='price-info'] [class*='price']",
        ".price-value",
        "span.price",
        "[class*='PriceValue']",
        "[class*='selling-price']",
        "[class*='price-value']",
        "[data-testid*='price']",
        ".pd-price strong",
        ".pd-price .price",
        # Precio en el botón de comprar
        "[class*='buy'] [class*='price']",
        "[class*='Price'] strong",
    ]

    for sel in selectors:
        try:
            element = page.locator(sel).first
            if await element.count() > 0:
                text = await element.inner_text()
                price = parse_price(text)
                if price:
                    print(f"✅ Precio encontrado con selector '{sel}': {text}")
                    return price
        except Exception:
            continue

    # Estrategia 2: Buscar en todo el texto visible algo que parezca precio ARS
    try:
        body_text = await page.inner_text("body")
        # Buscar patrones como $1.299.999 o $ 1.299.999
        price_patterns = re.findall(r"\$\s?[\d.]+(?:,\d{2})?", body_text)
        if price_patterns:
            for pattern in price_patterns:
                price = parse_price(pattern)
                if price and price > 100_000:  # Filtrar precios de cuotas (más bajos)
                    print(f"✅ Precio encontrado por regex en body: {pattern}")
                    return price
    except Exception as e:
        print(f"⚠️  Error buscando por regex: {e}")

    # Estrategia 3: Buscar en JSON-LD (structured data)
    try:
        json_ld_scripts = await page.locator('script[type="application/ld+json"]').all()
        for script in json_ld_scripts:
            content = await script.inner_text()
            try:
                data = json.loads(content)
                # Puede ser una lista o un objeto
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if "offers" in item:
                        offers = item["offers"]
                        if isinstance(offers, dict):
                            offers = [offers]
                        for offer in offers:
                            if "price" in offer:
                                price = float(offer["price"])
                                print(f"✅ Precio encontrado en JSON-LD: {price}")
                                return price
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
    except Exception as e:
        print(f"⚠️  Error buscando JSON-LD: {e}")

    # Estrategia 4: Interceptar respuestas de API internas que contengan precio
    # (esto se configura antes de navegar, ver get_price)

    return None


async def get_price() -> float | None:
    """Abre la página con Playwright y extrae el precio."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1920,1080",
            ],
        )

        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="es-AR",
            timezone_id="America/Argentina/Buenos_Aires",
            extra_http_headers={
                "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Sec-CH-UA": '"Chromium";v="131", "Not_A_Brand";v="24"',
                "Sec-CH-UA-Mobile": "?0",
                "Sec-CH-UA-Platform": '"Windows"',
            },
        )

        # Ocultar que es Playwright / headless
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['es-AR', 'es', 'en']
            });
            window.chrome = { runtime: {} };
            // Ocultar headless
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
            Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
        """)

        page = await context.new_page()

        # Interceptar respuestas de API que puedan contener precios
        api_price = {"value": None}

        async def handle_response(response):
            url = response.url
            if any(kw in url.lower() for kw in ["price", "sku", "product", "offer", "p6v2"]):
                try:
                    body = await response.text()
                    if "$" in body or "price" in body.lower():
                        data = json.loads(body)
                        # Buscar recursivamente campos de precio
                        price = find_price_in_json(data)
                        if price:
                            print(f"✅ Precio interceptado de API ({url[:80]}...): {price}")
                            api_price["value"] = price
                except Exception:
                    pass

        page.on("response", handle_response)

        # Navegar con domcontentloaded (más rápido y menos propenso a timeout)
        print("🌐 Navegando a la página...")
        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"⚠️  Error en navegación inicial: {e}")
            print("🔄 Reintentando con timeout extendido...")
            try:
                await page.goto(URL, wait_until="commit", timeout=90000)
            except Exception as e2:
                print(f"❌ Falló también el reintento: {e2}")
                await browser.close()
                return None

        # Esperar a que cargue el JavaScript del precio
        print("⏳ Esperando carga de JS...")
        await page.wait_for_timeout(8000)

        # Hacer scroll para disparar lazy-loading
        await page.evaluate("window.scrollBy(0, 300)")
        await page.wait_for_timeout(2000)

        # Intentar extraer del DOM
        price = await try_extract_price_from_page(page)

        # Si no encontramos en el DOM, verificar si lo interceptamos de una API
        if price is None and api_price["value"]:
            price = api_price["value"]

        # Debug: si no encontramos nada, guardar HTML y screenshot
        if price is None:
            html = await page.content()
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(html)
            try:
                await page.screenshot(path="debug_screenshot.png", full_page=False)
                print("📸 Screenshot guardado en debug_screenshot.png")
            except Exception:
                pass
            print("⚠️  HTML guardado en debug_page.html para inspeccionar selectores")
            print("💡 Tip: Revisá el HTML buscando el precio manualmente para actualizar los selectores")

        await browser.close()

        if price is None:
            print("❌ No se pudo extraer el precio.")
        return price


def find_price_in_json(data, depth=0) -> float | None:
    """Busca recursivamente un campo de precio en un dict/list JSON."""
    if depth > 10:
        return None
    if isinstance(data, dict):
        for key, val in data.items():
            if any(pk in key.lower() for pk in ["price", "precio", "amount"]):
                if isinstance(val, (int, float)) and val > 10000:
                    return float(val)
                if isinstance(val, str):
                    p = parse_price(val)
                    if p:
                        return p
            result = find_price_in_json(val, depth + 1)
            if result:
                return result
    elif isinstance(data, list):
        for item in data:
            result = find_price_in_json(item, depth + 1)
            if result:
                return result
    return None


def get_previous_price(sheet) -> float | None:
    """Devuelve el último precio guardado en el Sheet."""
    records = sheet.get_all_values()
    data_rows = [r for r in records[1:] if r[1]]
    if not data_rows:
        return None
    try:
        return float(data_rows[-1][1])
    except (ValueError, IndexError):
        return None


def log_to_sheets(sheet, price: float):
    """Agrega una fila con fecha y precio al Google Sheet."""
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    sheet.append_row([fecha, price, PRODUCT_NAME, URL])
    print(f"✅ Precio guardado en Sheets: ${price:,.0f} ({fecha})")


def send_alert(previous: float, current: float):
    """Envía un email de alerta si el precio bajó."""
    diff = previous - current
    pct = (diff / previous) * 100

    subject = f"📉 Bajó el precio: {PRODUCT_NAME}"
    body = f"""¡Buenas noticias! El precio del producto que estás siguiendo bajó.

Producto : {PRODUCT_NAME}
URL      : {URL}

Precio anterior : ${previous:,.0f}
Precio actual   : ${current:,.0f}
Diferencia      : -${diff:,.0f} ({pct:.1f}% menos)

—
Price Tracker automático 🤖
"""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"📧 Alerta enviada a {EMAIL_TO}")
    except Exception as e:
        print(f"❌ Error enviando email: {e}")


def get_sheet():
    """Autenticación con Google Sheets via Service Account."""
    creds_json = os.environ["GOOGLE_CREDENTIALS"]
    creds_dict = json.loads(creds_json)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)

    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    try:
        sheet = spreadsheet.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(SHEET_NAME, rows=1000, cols=5)
        sheet.append_row(["Fecha", "Precio (ARS)", "Producto", "URL"])
        print(f"✅ Hoja '{SHEET_NAME}' creada.")

    return sheet


async def main():
    print(f"🔍 Scrapeando precio de: {PRODUCT_NAME}")
    print(f"📅 Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # 1. Obtener precio actual
    current_price = await get_price()
    if current_price is None:
        print("❌ No se pudo obtener el precio. Abortando.")
        # Salimos con código 1 para que GitHub Actions lo marque como fallo
        raise SystemExit(1)

    print(f"💰 Precio actual: ${current_price:,.0f}")

    # 2. Conectar a Google Sheets
    sheet = get_sheet()

    # 3. Leer precio anterior
    previous_price = get_previous_price(sheet)

    # 4. Guardar en Sheets
    log_to_sheets(sheet, current_price)

    # 5. Enviar alerta si bajó
    if previous_price is not None:
        if current_price < previous_price:
            print(
                f"📉 El precio bajó de ${previous_price:,.0f} a ${current_price:,.0f}. Enviando alerta..."
            )
            send_alert(previous_price, current_price)
        elif current_price > previous_price:
            diff = current_price - previous_price
            print(
                f"📈 Subió (anterior: ${previous_price:,.0f}, cambio: +${diff:,.0f})"
            )
        else:
            print(f"➡️  Sin cambio: ${current_price:,.0f}")
    else:
        print("ℹ️  Primera ejecución, no hay precio anterior para comparar.")


if __name__ == "__main__":
    asyncio.run(main())
