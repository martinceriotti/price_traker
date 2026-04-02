# 📊 Price Tracker — Samsung TV (o cualquier producto)

Rastrea el precio de un producto web todos los días, lo guarda en Google Sheets
y te manda un email si el precio baja. Corre gratis con GitHub Actions.

---

## Archivos del proyecto

```
price-tracker/
├── scraper.py                        ← script principal
├── .github/
│   └── workflows/
│       └── track.yml                 ← automatización diaria
└── README.md
```

---

## Configuración paso a paso

### 1. Crear el repositorio en GitHub

1. Entrá a [github.com](https://github.com) → **New repository**
2. Poné un nombre (ej: `price-tracker`)
3. Dejalo **Private** (para que nadie vea tus credenciales)
4. Subí los archivos `scraper.py` y `.github/workflows/track.yml`

---

### 2. Crear el Google Sheet

1. Abrí [sheets.google.com](https://sheets.google.com) y creá un sheet nuevo
2. Llamalo "Price Tracker" (o lo que quieras)
3. Copiá el **ID** de la URL:
   ```
   https://docs.google.com/spreadsheets/d/  👉 ESTE_ES_EL_ID  /edit
   ```
   Guardalo, lo vas a necesitar después.

---

### 3. Crear una Service Account de Google (para que el script pueda escribir en el Sheet)

1. Entrá a [console.cloud.google.com](https://console.cloud.google.com)
2. Creá un proyecto nuevo (ej: "price-tracker")
3. Activá estas APIs:
   - **Google Sheets API**
   - **Google Drive API**
4. Ir a **IAM & Admin → Service Accounts → Create Service Account**
   - Nombre: `price-tracker`
   - Rol: **Editor**
5. En la service account creada → **Keys → Add Key → JSON**
   - Se descarga un archivo `.json` → guardalo, lo necesitás abajo
6. **Compartí el Google Sheet** con el email de la service account
   (se ve en el JSON como `"client_email": "price-tracker@...iam.gserviceaccount.com"`)
   - Abrí el Sheet → Compartir → pegá ese email → Editor

---

### 4. Obtener contraseña de aplicación de Gmail (para las alertas)

> ⚠️ No uses tu contraseña normal de Gmail. Necesitás una "App Password".

1. Entrá a [myaccount.google.com/security](https://myaccount.google.com/security)
2. Activá **Verificación en dos pasos** si no la tenés
3. Buscá **App passwords** → creá una nueva (nombre: "price-tracker")
4. Copiá la contraseña de 16 caracteres que aparece

---

### 5. Cargar los secrets en GitHub

En tu repositorio de GitHub → **Settings → Secrets and variables → Actions → New repository secret**

Cargá estos 5 secrets:

| Secret               | Valor                                                              |
|----------------------|--------------------------------------------------------------------|
| `SPREADSHEET_ID`     | El ID del Google Sheet (paso 2)                                    |
| `GOOGLE_CREDENTIALS` | El contenido **completo** del archivo JSON de la service account   |
| `EMAIL_FROM`         | Tu Gmail (ej: `tumail@gmail.com`)                                  |
| `EMAIL_PASSWORD`     | La App Password de 16 caracteres (paso 4)                         |
| `EMAIL_TO`           | El email donde recibir alertas (puede ser el mismo)                |

Para `GOOGLE_CREDENTIALS`: abrí el archivo `.json` descargado, seleccioná **todo** el contenido y pegalo como valor del secret.

---

### 6. Probar manualmente

Una vez cargados los secrets:

1. Ir a **Actions** en tu repositorio
2. Clic en **Price Tracker Diario**
3. Clic en **Run workflow**

Si todo está bien, vas a ver los logs en verde y el precio aparecer en tu Google Sheet.

---

## Cambiar el producto a rastrear

Editá estas líneas en `scraper.py`:

```python
URL          = "https://www.samsung.com/ar/..."   # ← tu URL
PRODUCT_NAME = "Nombre del producto"               # ← para el email
```

Para encontrar el selector CSS correcto del precio:
1. Abrí la página en Chrome
2. Clic derecho sobre el precio → **Inspeccionar**
3. Clic derecho sobre el elemento → **Copy → Copy selector**
4. Reemplazalo en la lista `selectors` dentro de `get_price()`

---

## Horario de ejecución

El workflow corre a las **9:00 AM hora Argentina** todos los días.
Para cambiar el horario, editá esta línea en `track.yml`:

```yaml
- cron: "0 12 * * *"   # UTC — Argentina es UTC-3
```

Usá [crontab.guru](https://crontab.guru) para generar el cron que necesites.

---

## Resultado en Google Sheets

La hoja **Historial** se va llenando así:

| Fecha            | Precio (ARS) | Producto              | URL         |
|------------------|--------------|-----------------------|-------------|
| 2025-01-15 09:00 | 1299999      | Samsung TV OLED S90F  | https://... |
| 2025-01-16 09:00 | 1199999      | Samsung TV OLED S90F  | https://... |

Podés agregar un gráfico en Sheets para visualizar la evolución del precio.
