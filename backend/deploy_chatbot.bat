@echo off
setlocal enabledelayedexpansion

echo ===============================
echo AUTENTICANDO CON GCLOUD...
echo ===============================
gcloud auth login

echo ===============================
echo INICIANDO BUILD EN CLOUD BUILD...
echo ===============================
gcloud builds submit --tag us-central1-docker.pkg.dev/advanced-analytics-dev-440814/docker-repo/chatbot-comercial

echo ===============================
echo HACIENDO DEPLOY A CLOUD RUN...
echo ===============================
gcloud run deploy chatbot-comercial ^
  --image us-central1-docker.pkg.dev/advanced-analytics-dev-440814/docker-repo/chatbot-comercial ^
  --platform managed ^
  --region us-central1

echo ===============================
echo OBTENIENDO ID_TOKEN PARA PRUEBA...
echo ===============================
gcloud auth print-identity-token > token.txt
set /p ID_TOKEN=<token.txt
del token.txt

echo ===============================
echo PROBANDO LA API CON CURL...
echo ===============================
curl -X POST https://chatbot-comercial-386846500093.us-central1.run.app/ ^
  -H "Authorization: Bearer %ID_TOKEN%" ^
  -H "Content-Type: application/json" ^
  -d "{\"pregunta\": \"¿Quién atiende la cuenta Natura?\"}"


echo.
echo ===============================
echo ✅ DEPLOY + TEST COMPLETADO
echo ===============================
pause