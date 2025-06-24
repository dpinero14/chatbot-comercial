# 🤖 Chatbot Comercial - Andreani

Este proyecto contiene el backend y la definición del API Gateway para el chatbot comercial.

## 📁 Estructura

- `backend/`: código Python + Docker para servir la API
- `openapi/`: archivo OpenAPI usado por API Gateway
- `.bat` y `Dockerfile`: permiten deploy y test locales o en Cloud Run

## 🚀 Cómo correr localmente

```bash
docker run -p 8080:8080 ^
 -e GOOGLE_APPLICATION_CREDENTIALS=/app/sa-key.json ^
 -v C:\ruta\a\svc-drive-reader.json:/app/sa-key.json ^
 chatbot-comercial
