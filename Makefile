.PHONY: up down logs setup dev-api clean restart

# Levantar todo el entorno (TestLink + API)
up:
	@echo "🚀 Iniciando servicios de TestLink..."
	cd testlink && docker-compose up -d
	@echo "⏳ Esperando inicialización de base de datos..."
	@sleep 5
	@echo "🚀 Construyendo e iniciando MCP API..."
	cd mcp-api && docker build -t testlink-mcp-api .
	-docker rm -f testlink-mcp-api 2>/dev/null
	docker run -d --name testlink-mcp-api \
		--network testlink_testlink-network \
		-p 8012:8012 \
		-v $(shell pwd)/mcp-api/.env:/app/.env \
		testlink-mcp-api
	@echo "✅ Entorno levantado. TestLink: http://localhost:8080 | API: http://localhost:8012"

# Detener todo
down:
	@echo "🛑 Deteniendo servicios..."
	cd testlink && docker-compose down
	-docker rm -f testlink-mcp-api

# Ver logs unificados
logs:
	@echo "📋 Mostrando logs (Ctrl+C para salir)..."
	docker logs -f testlink-mcp-api & \
	cd testlink && docker-compose logs -f

# Configuración inicial automática
setup:
	@echo "⚙️ Ejecutando script de configuración..."
	./setup-testlink.sh

# Desarrollo local de la API (Hot Reload)
dev-api:
	cd mcp-api && python3 dev_server.py

# Limpiar todo (contenedores, volúmenes e imágenes)
clean:
	@echo "🗑️ Eliminando contenedores, volúmenes e imágenes..."
	-docker rm -f testlink-mcp-api
	-docker rmi testlink-mcp-api
	cd testlink && docker-compose down -v
	@echo "✅ Limpieza completa."

restart: clean up