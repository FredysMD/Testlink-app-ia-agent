#!/bin/bash

# Script para configurar TestLink automáticamente
echo "Configurando TestLink..."

# Esperar a que el contenedor testlink-app esté listo
echo "Esperando a que el contenedor testlink-app esté en ejecución..."
while [ "$(docker inspect -f '{{.State.Running}}' testlink-app 2>/dev/null)" != "true" ]; do
    sleep 2
done

# Corregir error de conexión a BD: Asegurar que apunte al contenedor mariadb y use las credenciales correctas
echo "Aplicando corrección de configuración de base de datos..."
docker exec testlink-app bash -c "cat > /usr/share/nginx/testlink/config_db.inc.php <<EOF
<?php
define('DB_TYPE', 'mysql');
define('DB_USER', 'testlink');
define('DB_PASS', 'testlink');
define('DB_HOST', 'mariadb');
define('DB_NAME', 'testlink');
define('DB_TABLE_PREFIX', '');
EOF"

if [ $? -eq 0 ]; then
    echo "Configuración de base de datos aplicada correctamente."
else
    echo "Error al aplicar configuración. Asegúrate de que el contenedor esté corriendo."
    exit 1
fi

# Esperar a que TestLink esté disponible
until curl -s http://localhost:8080/login.php > /dev/null; do
    echo "Esperando a que TestLink esté disponible..."
    sleep 5
done

echo "TestLink está disponible. Configurando API key..."

# Esperar a que MariaDB esté lista para conexiones
sleep 5

# Verificar si la tabla users existe. Si no, intentar reiniciar para forzar instalación.
if ! docker exec testlink-mariadb mysql -u testlink -ptestlink testlink -e "DESCRIBE users;" >/dev/null 2>&1; then
    echo "La tabla 'users' no existe. Inicializando base de datos manualmente..."
    
    # Rutas de scripts SQL en el contenedor
    TL_ROOT="/usr/share/nginx/testlink"
    
    # Importar tablas y datos directamente desde los archivos del contenedor
    echo "Importando esquema..."
    docker exec testlink-app cat $TL_ROOT/install/sql/mysql/testlink_create_tables.sql | docker exec -i testlink-mariadb mysql -u testlink -ptestlink testlink
    
    echo "Importando datos por defecto..."
    docker exec testlink-app cat $TL_ROOT/install/sql/mysql/testlink_create_default_data.sql | docker exec -i testlink-mariadb mysql -u testlink -ptestlink testlink
    
    if [ $? -eq 0 ]; then
        echo "Base de datos inicializada manualmente."
    else
        echo "Error al importar SQL. Verificando si los archivos existen..."
        docker exec testlink-app ls -l $TL_ROOT/install/sql/mysql/
    fi
fi

# Intentar configurar usuario (ahora debería existir la tabla)
if docker exec testlink-mariadb mysql -u testlink -ptestlink testlink -e "DESCRIBE users;" >/dev/null 2>&1; then
    # Crear usuario admin con API key fija si no existe
    docker exec testlink-mariadb mysql -u testlink -ptestlink testlink -e "
    INSERT IGNORE INTO users (login, password, email, first, last, locale, default_testproject_id, active, script_key) 
    VALUES ('admin', MD5('admin'), 'admin@testlink.local', 'Test', 'Admin', 'en_GB', 1, 1, '0286d3623c37abb27c0de5fe5de283f6');

    UPDATE users SET script_key = '0286d3623c37abb27c0de5fe5de283f6' WHERE login = 'admin';
    " 2>/dev/null
    
    if [ $? -eq 0 ]; then
        echo "Usuario admin y API Key configurados."
    else
        echo "Advertencia: Falló la inserción del usuario, pero la BD parece existir."
    fi
else
    echo "Error Crítico: La tabla 'users' sigue sin existir."
    echo "TestLink no pudo instalar la base de datos. Revisa los logs: docker logs testlink-app"
    exit 1
fi

echo "Configuración completada"