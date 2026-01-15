# TestLink MCP API

API FastAPI que conecta con TestLink via XML-RPC para procesamiento de lenguaje natural.

## 🚀 Inicio Rápido

### Opción 1: Con TestLink real
```bash
# Construir imagen
docker build -t testlink-mcp-api .

# Ejecutar con volumen para .env dinámico
docker run -d --name testlink-mcp-api \
  --network testlink_testlink-network \
  -p 8012:8012 \
  -v $(pwd)/.env:/app/.env \
  testlink-mcp-api
```

### Opción 2: Modo Demo (sin TestLink)
```bash
docker run -d --name testlink-mcp-api \
  -p 8012:8012 \
  -v $(pwd):/app \
  python:3.11-slim \
  sh -c "cd /app && pip install fastapi uvicorn python-dotenv && python demo_api.py"
```

## ⚙️ Configuración

### Variables de entorno (.env)
```bash
# Conexión TestLink
TESTLINK_URL=http://testlink:80/lib/api/xmlrpc/v1/xmlrpc.php
TESTLINK_API_KEY=tu_clave_api_aqui

# Configuración API
API_HOST=0.0.0.0
API_PORT=8012
```

### Actualizar API Key
1. Generar clave en TestLink (My Settings → API interface)
2. Editar `.env` con nueva clave
3. Reiniciar: `docker restart testlink-mcp-api`

## 🔗 Endpoints

- **Health**: http://localhost:8012/testlink/health
- **Docs**: http://localhost:8012/docs
- **Prompt**: POST http://localhost:8012/testlink/prompt

## 🧪 Ejemplos de uso

```bash
# Listar proyectos
curl -X POST "http://localhost:8012/testlink/prompt" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "listar proyectos"}'

# Buscar casos de prueba
curl -X POST "http://localhost:8012/testlink/prompt" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "¿Qué casos de prueba hay sobre AUTH?"}'

# Crear proyecto
curl -X POST "http://localhost:8012/testlink/prompt" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "crear proyecto Mi Nuevo Proyecto"}'
```

## 🔧 Desarrollo

### Instalación de dependencias
```bash
pip install -r requirements.txt
```

### Hot reload local
```bash
python dev_server.py
```

### Docker Compose (desarrollo)
```bash
docker-compose up -d
```

## 🔍 Troubleshooting

### Error "invalid developer key"
- Generar nueva API key en TestLink
- Actualizar `.env`
- Reiniciar contenedor

### Error de conexión
- Verificar que TestLink esté ejecutándose
- Verificar red Docker: `testlink_testlink-network`
- URL debe usar nombre del servicio: `testlink:80`