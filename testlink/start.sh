#!/bin/bash

echo "🚀 Iniciando TestLink..."

# Verificar si Docker está ejecutándose
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker no está ejecutándose"
    exit 1
fi

# Iniciar TestLink
docker-compose up -d

echo "✅ TestLink iniciado en http://localhost:8080"
echo ""
echo "📋 Próximos pasos:"
echo "1. Accede a http://localhost:8080"
echo "2. Completa la instalación inicial"
echo "3. Genera API key en 'My Settings' → 'API interface'"
echo "4. Actualiza .env con tu API key"