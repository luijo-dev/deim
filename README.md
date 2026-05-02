# DEIM — Comparador DIAN vs Platform (MVP)

Aplicación Streamlit para comparar declaraciones de importación DIAN contra documentos de plataforma/cliente.

## Requisitos locales

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)

## Desarrollo

```bash
# Instalar dependencias
make setup

# Ejecutar en modo desarrollo (reload automático)
make dev

# Ejecutar en modo producción local
make run

# Tests y calidad
make test
make check
```

## Deploy en Google Cloud Run

### Prerrequisitos

- Proyecto GCP con las APIs habilitadas:
  - Cloud Run API
  - Cloud Build API
  - Artifact Registry API
- Cuenta de servicio con permisos:
  - `roles/run.admin`
  - `roles/cloudbuild.builds.editor`
  - Lectura/escritura en Artifact Registry
- [gcloud CLI](https://cloud.google.com/sdk/docs/install) autenticado

### Variables de entorno del Makefile

| Variable   | Default                     | Descripción                          |
|------------|-----------------------------|--------------------------------------|
| `PROJECT_ID` | Proyecto activo en gcloud   | Proyecto GCP                         |
| `REGION`     | `us-central1`               | Región de despliegue                 |
| `SERVICE`    | `deim`                      | Nombre del servicio Cloud Run        |
| `IMAGE_URI`  | `gcr.io/$PROJECT_ID/$SERVICE` | URI de la imagen en Artifact Registry |

### Comandos de deploy

```bash
# Deploy con valores por defecto
make deploy

# Deploy a otra región o con otro nombre
make deploy REGION=us-east1 SERVICE=deim-staging
```

El target `make deploy` ejecuta en orden:
1. `gcloud builds submit` — construye la imagen Docker usando `cloudbuild.yaml`
2. `gcloud run deploy` — despliega el servicio con:
   - Puerto `8080`
   - **Sin acceso público** (`--no-allow-unauthenticated`)

### Obtener la URL del servicio

```bash
make service-url
```

## Configuración recomendada de Cloud Run

Ajusta estos parámetros según el comportamiento observado:

| Parámetro         | Recomendación inicial | Notas                                                                 |
|-------------------|-----------------------|-----------------------------------------------------------------------|
| **Min instances** | `0`                   | Escala a cero = menor costo. Usa `1` solo si los cold starts molestan. |
| **Max instances** | `10`                  | Límite de concurrencia según uso.                                      |
| **Memory**        | `2 GiB`               | PyMuPDF + Polars + PDFs en memoria pueden presionar RAM.               |
| **CPU**           | `1`                   | Aumentar si el procesamiento de PDFs es lento.                         |
| **Timeout**       | `300s` (5 min)        | Ajustar hasta `900s` (15 min) si los PDFs grandes tardan más.          |
| **Concurrency**   | `1`                   | Streamlit mantiene sesiones; subir con precaución y métricas.          |

Para cambiar parámetros después del deploy:

```bash
gcloud run services update deim \
  --region us-central1 \
  --memory 2Gi \
  --timeout 300s \
  --concurrency 1 \
  --min-instances 0
```

## Seguridad

- **No uses `--allow-unauthenticated`** en producción si manejas documentos sensibles.
- Concede acceso por usuario/cuenta de servicio con IAM o IAP.
- El servicio se inicia con `--server.headless=true` para evitar abrir navegador dentro del contenedor.
- Los PDFs subidos se procesan **en memoria**; no se escriben a disco en el flujo productivo.

## Arquitectura del contenedor

- Base: `python:3.13-slim`
- Gestor de dependencias: `uv` (lockfile reproducible)
- Puerto: `8080` (o el valor de la variable `$PORT` que provee Cloud Run)
- Entrypoint: `streamlit run main.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true`

## Limitaciones conocidas

- **Cold starts**: con `min-instances=0`, la primera visita después de inactividad puede tardar unos segundos.
- **WebSockets / sesiones**: Cloud Run soporta WebSockets, pero están sujetos al request timeout. Streamlit puede reconectar automáticamente.
- **Memoria**: PDFs muy grandes pueden agotar la RAM asignada; monitorea con Cloud Logging/Metrics.

## Rollback

Si una versión falla, revierte tráfico a la revisión anterior:

```bash
gcloud run services update-traffic deim \
  --region us-central1 \
  --to-revisions PREVIA_REVISION=100
```

O re-deploy usando una imagen anterior:

```bash
gcloud run deploy deim --image IMAGEN_ANTERIOR --region us-central1
```
