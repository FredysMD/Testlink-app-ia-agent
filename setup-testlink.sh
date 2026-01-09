#!/bin/bash

# Script para configurar TestLink automáticamente
echo "Configurando TestLink..."

# Esperar a que TestLink esté disponible
until curl -s http://localhost:8080/login.php > /dev/null; do
    echo "Esperando a que TestLink esté disponible..."
    sleep 5
done

echo "TestLink está disponible. Configurando API key..."

# Crear usuario admin con API key fija si no existe
docker exec testlink-app mysql -h postgres -u testlink -ptestlink123 testlink -e "
INSERT IGNORE INTO users (login, password, email, first, last, locale, default_testproject_id, active, script_key) 
VALUES ('admin', MD5('admin'), 'admin@testlink.local', 'Test', 'Admin', 'en_GB', 1, 1, '0286d3623c37abb27c0de5fe5de283f6');

UPDATE users SET script_key = '0286d3623c37abb27c0de5fe5de283f6' WHERE login = 'admin';
" 2>/dev/null || echo "Base de datos no disponible aún"

echo "Configuración completada"