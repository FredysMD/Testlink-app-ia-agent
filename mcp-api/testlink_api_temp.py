#!/usr/bin/env python3
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title=os.getenv("API_TITLE", "TestLink MCP API"),
    version=os.getenv("API_VERSION", "1.0.0")
)

class PromptRequest(BaseModel):
    prompt: str

@app.post("/testlink/prompt")
async def process_testlink_prompt(request: PromptRequest):
    testlink_url = os.getenv("TESTLINK_URL")
    api_key = "d02f9418ca5d547ec29c1fbf7019daa5"
    
    return {
        "success": False,
        "message": "Para usar la API, necesitas generar una clave API válida en TestLink:\n1. Accede a http://localhost:8080\n2. Inicia sesión (admin/admin)\n3. Ve a 'My Settings' → 'API interface'\n4. Genera una nueva clave API\n5. Actualiza el archivo .env con la nueva clave",
        "action_taken": "configuration_required",
        "data": {
            "testlink_url": testlink_url,
            "api_key_preview": f"{api_key[:10]}..." if api_key else "No configurada",
            "instructions": [
                "Acceder a TestLink en http://localhost:8080",
                "Iniciar sesión con admin/admin",
                "Ir a My Settings → API interface", 
                "Generar nueva clave API",
                "Actualizar .env con la nueva clave",
                "Reiniciar el contenedor: docker restart testlink-mcp-api"
            ]
        }
    }

@app.get("/testlink/health")
async def health_check():
    return {"status": "healthy", "service": "TestLink MCP API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("testlink_api_temp:app", host="0.0.0.0", port=8012)