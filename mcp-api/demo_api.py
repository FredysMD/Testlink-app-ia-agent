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

# Mock data para demostración
MOCK_PROJECTS = [
    {
        "id": "1",
        "name": "DEMO PROJECT",
        "prefix": "DEMO",
        "active": "1",
        "notes": "Proyecto de demostración"
    }
]

MOCK_TEST_CASES = [
    {
        "id": "1",
        "name": "Test Login Functionality",
        "summary": "Verificar que el usuario puede iniciar sesión correctamente",
        "project": "DEMO PROJECT",
        "suite": "Authentication Tests"
    },
    {
        "id": "2", 
        "name": "Test Password Reset",
        "summary": "Verificar que el usuario puede restablecer su contraseña",
        "project": "DEMO PROJECT",
        "suite": "Authentication Tests"
    }
]

@app.post("/testlink/prompt")
async def process_testlink_prompt(request: PromptRequest):
    prompt_lower = request.prompt.lower()
    
    if "listar proyectos" in prompt_lower or "list projects" in prompt_lower:
        return {
            "success": True,
            "message": f"Se encontraron {len(MOCK_PROJECTS)} proyectos",
            "action_taken": "list_projects",
            "data": MOCK_PROJECTS
        }
    elif "casos" in prompt_lower or "pruebas" in prompt_lower or "test" in prompt_lower:
        return {
            "success": True,
            "message": f"Se encontraron {len(MOCK_TEST_CASES)} casos de prueba",
            "action_taken": "list_test_cases",
            "data": MOCK_TEST_CASES
        }
    elif "crear proyecto" in prompt_lower:
        return {
            "success": True,
            "message": "Proyecto creado exitosamente (modo demo)",
            "action_taken": "create_project",
            "data": {"id": "2", "name": "Nuevo Proyecto", "status": "created"}
        }
    else:
        return {
            "success": True,
            "message": "API funcionando en modo demo. Comandos disponibles: 'listar proyectos', 'casos de prueba', 'crear proyecto [nombre]'",
            "action_taken": "help",
            "data": {
                "available_commands": [
                    "listar proyectos",
                    "casos de prueba", 
                    "crear proyecto [nombre]"
                ]
            }
        }

@app.get("/testlink/health")
async def health_check():
    return {"status": "healthy", "service": "TestLink MCP API (Demo Mode)"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("demo_api:app", host="0.0.0.0", port=8012)