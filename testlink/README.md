# TestLink Setup

## 🚀 Inicio Rápido

```bash
# Levantar TestLink + PostgreSQL
docker-compose up -d

# Verificar estado
docker logs testlink-app
docker logs testlink-postgres
```

## ⚙️ Configuración

### Primera vez
1. Esperar 2-3 minutos para que PostgreSQL inicialice
2. Acceder a http://localhost:8080
3. Completar instalación inicial de TestLink
4. Crear usuario admin/admin
5. Ir a "My Settings" → "API interface"
6. Generar API key
7. Copiar la clave generada

### Actualizar API Key
```bash
# Editar archivo .env
TESTLINK_API_KEY=tu_nueva_clave_aqui

# Reiniciar MCP API
docker restart testlink-mcp-api
```

## 🔧 Comandos útiles

```bash
# Ver logs
docker logs testlink-app
docker logs testlink-postgres

# Reiniciar servicios
docker-compose restart

# Detener todo
docker-compose down

# Limpiar volúmenes (CUIDADO: borra datos)
docker-compose down -v
```

## 📊 Persistencia

- Base de datos PostgreSQL persistente
- Archivos de TestLink en volúmenes
- Configuración mantenida entre reinicios