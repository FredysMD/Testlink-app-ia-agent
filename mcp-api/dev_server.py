#!/usr/bin/env python3
import uvicorn
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

if __name__ == "__main__":
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", 8000))
    log_level = os.getenv("LOG_LEVEL", "info")
    
    print("🔥 Modo DESARROLLO - Hot Reload ACTIVADO")
    print(f"🚀 API TestLink en {host}:{port}")
    print(f"📖 Documentación: http://{host}:{port}/docs")
    print(f"🔄 Los cambios se reflejan automáticamente")
    
    uvicorn.run(
        "testlink_api:app",
        host=host,
        port=port,
        log_level=log_level,
        reload=True,
        reload_dirs=["./"],  # Vigilar directorio actual
        reload_includes=["*.py"]  # Solo archivos Python
    )