"""
Configuración centralizada — todas las variables de entorno del proyecto.
"""
import logging
import os

from dotenv import load_dotenv

load_dotenv()

# --- TestLink ---
TESTLINK_URL: str = os.getenv("TESTLINK_URL", "http://testlink:80/lib/api/xmlrpc/v1/xmlrpc.php")
TESTLINK_API_KEY: str = os.getenv("TESTLINK_API_KEY", "")

# --- Google Gemini ---
GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MAX_TOOL_ITERATIONS: int = int(os.getenv("MAX_TOOL_ITERATIONS", "5"))

# --- FastAPI ---
API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("API_PORT", "8012"))
API_TITLE: str = os.getenv("API_TITLE", "TestLink MCP API")
API_VERSION: str = os.getenv("API_VERSION", "1.0.0")

# --- Logging ---
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# --- System prompt del agente ---
SYSTEM_PROMPT = """Eres un Asistente experto en QA y TestLink. Tu función es de LECTURA y BÚSQUEDA.

INSTRUCCIONES:
- Usa `search_tests` para buscar por palabras clave.
- Usa `list_test_cases_in_suite` para listar casos de una suite específica.
- Usa `list_test_suites` para descubrir suites disponibles en un proyecto.
- Puedes encadenar múltiples herramientas para responder completamente.
- Responde siempre en el idioma del usuario.

FORMATO DE RESPUESTA — MUY IMPORTANTE:
- NUNCA generes tablas Markdown ni listas de texto con los resultados.
- El campo `message` debe ser SOLO un resumen breve: cuántos resultados se encontraron y en qué contexto.
- Los datos detallados (casos, suites, proyectos, etc.) ya se retornan estructurados en el campo `data`, NO los repitas en `message`.
- Ejemplo correcto de `message`: "Se encontraron 3 casos de prueba relacionados con 'Login' en el proyecto 'Agente TestLink'."
- Ejemplo INCORRECTO: listar los casos con nombres, IDs o tablas dentro de `message`."""

# --- Definición de herramientas del agente ---
TOOLS = [
    {
        "name": "list_projects",
        "description": "Get all test projects",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "read_test_case",
        "description": "Fetch complete test case data by external ID",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "test_case_external_id": {"type": "STRING", "description": "e.g. PROJ-1"},
                "project_name": {"type": "STRING"},
            },
            "required": ["test_case_external_id"],
        },
    },
    {
        "name": "get_test_case_details",
        "description": "Get detailed info (summary, preconditions, steps) of a test case",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "test_case_external_id": {"type": "STRING"},
                "project_name": {"type": "STRING"},
            },
            "required": ["test_case_external_id"],
        },
    },
    {
        "name": "list_test_suites",
        "description": "Get test suites for a project",
        "parameters": {
            "type": "OBJECT",
            "properties": {"project_name": {"type": "STRING"}},
            "required": ["project_name"],
        },
    },
    {
        "name": "list_test_plans",
        "description": "List all test plans for a project",
        "parameters": {
            "type": "OBJECT",
            "properties": {"project_name": {"type": "STRING"}},
            "required": ["project_name"],
        },
    },
    {
        "name": "list_builds",
        "description": "List all builds for a test plan",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "plan_name": {"type": "STRING"},
                "project_name": {"type": "STRING"},
            },
            "required": ["plan_name", "project_name"],
        },
    },
    {
        "name": "read_test_execution",
        "description": "Get last execution result for a test case in a plan",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "test_case_external_id": {"type": "STRING"},
                "plan_name": {"type": "STRING"},
                "project_name": {"type": "STRING"},
            },
            "required": ["test_case_external_id", "plan_name", "project_name"],
        },
    },
    {
        "name": "list_test_cases_in_suite",
        "description": "Get all test cases in a specific test suite (searches recursively)",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "suite_name": {"type": "STRING"},
                "project_name": {"type": "STRING"},
            },
            "required": ["suite_name", "project_name"],
        },
    },
    {
        "name": "list_requirements",
        "description": "Get all requirements for a project",
        "parameters": {
            "type": "OBJECT",
            "properties": {"project_name": {"type": "STRING"}},
            "required": ["project_name"],
        },
    },
    {
        "name": "search_tests",
        "description": "Search test cases by keyword in name, summary or steps",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "keyword": {"type": "STRING"},
                "project_name": {"type": "STRING", "description": "Optional: limit to specific project"},
            },
            "required": ["keyword"],
        },
    },
]
