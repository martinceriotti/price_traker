import asyncio
import os
import smtplib
import json
from datetime import datetime
from email.mime.text import MIMEText
from playwright.async_api import async_playwright
import gspread
from google.oauth2.service_account import Credentials

# ── Configuración ──────────────────────────────────────────────────────────────
URL = "https://www.samsung.com/ar/tvs/oled-tv/s90f-65-inch-oled-4k-smart-tv-qn65s90fagxzb/"
PRODUCT_NAME = "Samsung TV OLED S90F 65\""

# Google Sheets
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]   # ID del Google Sheet (ver README)
SHEET_NAME     = "Historial"

# Alerta por email (via Gmail)
EMAIL_FROM     = os.environ["EMAIL_FROM"]        # tu Gmail: ejemplo@gmail.com
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]    # contraseña de aplicación de Gmail
EMAIL_TO       = os.environ["EMAIL_TO"]          # destinatario (puede ser el mismo)
# ──────────────────────────────────────────────────────────────────────────────


async def get_price() -> float | None:
    """Abre la página con Playwright y extrae el precio."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1920,1080",
            ],
        )

        # Contexto que simula un navegador real
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="es-AR",
            timezone_id="America/Argentina/Buenos_Aires",
            extra_http_headers={
                "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            },
        )

        # Ocultamos que es Playwright
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            window.chrome = { runtime: {} };
        """)

        page = await context.new_page()

        # domcontentloaded es menos estricto que networkidle → no hace timeout
        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

        # Esperamos un poco a que cargue el JS del precio
        await page.wait_for_timeout(5000)

        # Esperamos que aparezca el precio (Samsung usa este selector)
        try:
            await page.wait_for_selector(".price-value, [class*='price']", timeout=20000)
        except Exception:
            print("⚠️  Selector de precio no encontrado, intentando igual...")

        # Intentamos varios selectores comunes de Samsung AR
        selectors = [
            ".price-value",
            "span.price",
            "[class*='price-value']",
            "[class*='selling-price']",
        ]
        raw_price = None
        for sel in selectors:
            element = page.locator(sel).first
            if await element.count() > 0:
                raw_price = await element.inner_text()
                break

        # Debug: si no encontramos precio, guardamos el HTML para inspeccionar
        if not raw_price:
            html = await page.content()
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("⚠️  HTML guardado en debug_page.html para inspeccionar selectores")

        await browser.close()

        if not raw_price:
            print("❌ No se pudo extraer el precio.")
            return None

        # Limpiamos: "$1.299.999" → 1299999.0
        cleaned = raw_price.replace("$", "").replace(".", "").replace(",", ".").strip()
        try:
            return float(cleaned)
        except ValueError:
            print(f"❌ No se pudo convertir '{raw_price}' a número.")
            return None


def get_previous_price(sheet) -> float | None:
    """Devuelve el último precio guardado en el Sheet."""
    records = sheet.get_all_values()
    # Fila 1 = encabezado, buscamos la última fila con datos
    data_rows = [r for r in records[1:] if r[1]]  # columna B = precio
    if not data_rows:
        return None
    try:
        return float(data_rows[-1][1])
    except (ValueError, IndexError):
        return None


def log_to_sheets(sheet, price: float):
    """Agrega una fila con fecha y precio al Google Sheet."""
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    sheet.append_row([fecha, price])
    print(f"✅ Precio guardado en Sheets: ${price:,.0f} ({fecha})")


def send_alert(previous: float, current: float):
    """Envía un email de alerta si el precio bajó."""
    diff = previous - current
    pct  = (diff / previous) * 100

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
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"📧 Alerta enviada a {EMAIL_TO}")
    except Exception as e:
        print(f"❌ Error enviando email: {e}")


def get_sheet():
    """Autenticación con Google Sheets via Service Account."""
    creds_json = os.environ["GOOGLE_CREDENTIALS"]  # JSON como string (ver README)
    creds_dict = json.loads(creds_json)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds  = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)

    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    # Crear hoja "Historial" si no existe
    try:
        sheet = spreadsheet.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(SHEET_NAME, rows=1000, cols=5)
        sheet.append_row(["Fecha", "Precio (ARS)", "Producto", "URL"])
        print(f"✅ Hoja '{SHEET_NAME}' creada.")

    return sheet


async def main():
    print(f"🔍 Scrapeando precio de: {PRODUCT_NAME}")

    # 1. Obtener precio actual
    current_price = await get_price()
    if current_price is None:
        print("❌ No se pudo obtener el precio. Abortando.")
        return

    print(f"💰 Precio actual: ${current_price:,.0f}")

    # 2. Conectar a Google Sheets
    sheet = get_sheet()

    # 3. Leer precio anterior (para comparar)
    previous_price = get_previous_price(sheet)

    # 4. Guardar en Sheets
    log_to_sheets(sheet, current_price)

    # 5. Enviar alerta si bajó
    if previous_price is not None:
        if current_price < previous_price:
            print(f"📉 El precio bajó de ${previous_price:,.0f} a ${current_price:,.0f}. Enviando alerta...")
            send_alert(previous_price, current_price)
        else:
            diff = current_price - previous_price
            print(f"📈 Sin baja (anterior: ${previous_price:,.0f}, cambio: +${diff:,.0f})")
    else:
        print("ℹ️  Primera ejecución, no hay precio anterior para comparar.")


if __name__ == "__main__":
    asyncio.run(main())
