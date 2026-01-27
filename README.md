# TestLink + MCP API Integration

Sistema completo de TestLink con API MCP para procesamiento de lenguaje natural, orquestado para facilitar el desarrollo y despliegue.

## 🚀 Inicio Rápido

### 1. Levantar todo el entorno
El proyecto incluye un `Makefile` para simplificar la gestión de contenedores.

```bash
make up
```

### 2. Levantar MCP API
```bash
cd ../mcp-api
docker build -t testlink-mcp-api .
docker run -d --name testlink-mcp-api \
  --network testlink_testlink-network \
  -p 8012:8012 \
  -v $(pwd)/.env:/app/.env \
  testlink-mcp-api
```

### 3. Verificar servicios
```bash
# TestLink
curl -s http://localhost:8080 | grep -o "login.php" && echo "TestLink OK"

# MCP API
curl -s http://localhost:8012/testlink/health
```

## ⚙️ Configuración

### TestLink API Key
1. Accede a http://localhost:8080
2. Inicia sesión (admin/admin)
3. Ve a "My Settings" → "API interface"
4. Genera nueva API key
5. Actualiza `mcp-api/.env`:
   ```
   TESTLINK_API_KEY=tu_nueva_clave_aqui
   ```
6. Reinicia MCP API:
   ```bash
   docker restart testlink-mcp-api
   ```

## 🧪 Pruebas

### Comandos disponibles
```bash
# Listar proyectos
curl -X POST "http://localhost:8012/testlink/prompt" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "listar proyectos"}'

# Buscar casos de prueba
curl -X POST "http://localhost:8012/testlink/prompt" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "¿Qué casos de prueba hay?"}'

# Crear proyecto
curl -X POST "http://localhost:8012/testlink/prompt" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "crear proyecto Mi Nuevo Proyecto"}'
```

## 📁 Estructura del Proyecto

```
testlink-app/
├── testlink/                 # TestLink con PostgreSQL
│   ├── docker-compose.yml    # TestLink + PostgreSQL
│   ├── Dockerfile           # TestLink con PHP XML
│   └── .env                 # Configuración DB
├── mcp-api/                 # API MCP
│   ├── testlink_api.py      # API principal
│   ├── demo_api.py          # API demo (sin auth)
│   ├── Dockerfile           # Container Python
│   └── .env                 # Configuración API
└── setup-testlink.sh        # Script de configuración
```

## 🔧 Desarrollo

### Modo Demo (sin TestLink)
```bash
cd mcp-api
docker run -d --name testlink-mcp-api \
  -p 8012:8012 \
  -v $(pwd):/app \
  python:3.11-slim \
  sh -c "cd /app && pip install fastapi uvicorn python-dotenv && python demo_api.py"
```

### Hot Reload
```bash
cd mcp-api
python dev_server.py
```

## 🐳 Docker Compose Completo

Para levantar todo el sistema:

```bash
# Desde testlink/
docker-compose up -d

# Esperar 30 segundos para PostgreSQL
sleep 30

# Desde mcp-api/
docker build -t testlink-mcp-api .
docker run -d --name testlink-mcp-api \
  --network testlink_testlink-network \
  -p 8012:8012 \
  -v $(pwd)/.env:/app/.env \
  testlink-mcp-api
```

## 🔍 Troubleshooting

### Error "invalid developer key"
1. Genera nueva API key en TestLink
2. Actualiza `mcp-api/.env`
3. Reinicia: `docker restart testlink-mcp-api`

### TestLink no responde
```bash
# Verificar logs
docker logs testlink-app
docker logs testlink-postgres

# Reiniciar servicios
cd testlink && docker-compose restart
```

### API no conecta a TestLink
- Verificar que ambos contenedores estén en la misma red
- URL debe ser: `http://testlink:80/lib/api/xmlrpc/v1/xmlrpc.php`

## 📊 Persistencia

- **Base de datos**: PostgreSQL con volumen persistente
- **Archivos TestLink**: Volúmenes para uploads y configuración
- **Configuración API**: Montada como volumen para cambios dinámicos

Los datos se mantienen entre reinicios de contenedores.

## 🌐 URLs

- **TestLink**: http://localhost:8080
- **MCP API**: http://localhost:8012
- **API Docs**: http://localhost:8012/docs
- **Health Check**: http://localhost:8012/testlink/health