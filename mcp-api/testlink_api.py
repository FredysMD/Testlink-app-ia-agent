#!/usr/bin/env python3
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncio
import json
from typing import Optional, Dict, Any, List, Union
import testlink
import traceback
import os
from dotenv import load_dotenv
import logging

# Intentar importar Google Generative AI
try:
    import google.generativeai as genai
    from google.ai.generativelanguage_v1beta.types import content
except ImportError:
    genai = None

# Cargar variables de entorno
load_dotenv()

# Configuración de Logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("testlink-mcp")

app = FastAPI(
    title=os.getenv("API_TITLE", "TestLink MCP API"),
    version=os.getenv("API_VERSION", "1.0.0")
)

class PromptRequest(BaseModel):
    prompt: str

class TestLinkMCPClient:
    def __init__(self):
        self.tl_client = None
        self.model = None
        if genai and os.getenv("GOOGLE_API_KEY"):
            genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
            model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
            self.model = genai.GenerativeModel(model_name)
            logger.info(f"Modelo Gemini inicializado: {model_name}")
        
    async def connect(self, url: str, api_key: str) -> bool:
        try:
            logger.info(f"Intentando conectar a TestLink en: {url}")
            masked_key = f"{api_key[:5]}...{api_key[-5:]}" if len(api_key) > 10 else "***"
            logger.debug(f"Usando API key: {masked_key}")
            
            self.tl_client = testlink.TestlinkAPIClient(url, api_key)
            # Test connection with a simple call
            try:
                about_info = self.tl_client.about()
                logger.info(f"Conexión exitosa a TestLink: {about_info}")
                return True
            except Exception as api_error:
                logger.error(f"Fallo en llamada API inicial: {api_error}")
                return False
        except Exception as e:
            logger.error(f"Error de conexión: {e}", exc_info=True)
            return False
    
    async def process_prompt(self, prompt: str) -> Dict[str, Any]:
        """Procesa el prompt usando arquitectura RAG + Strand Agent"""
        if not self.model:
            return {
                "success": False,
                "message": "Modo Agente no disponible. Configura GOOGLE_API_KEY y asegúrate de tener 'google-generativeai' instalado."
            }

        try:
            # 1. RAG: Obtener contexto relevante de TestLink
            context = await self._get_rag_context(prompt)
            
            # 2. Definir Herramientas (Tools) para el Agente
            tools = self._get_tools_definition()
            
            # 3. Ejecutar Strand Agent
            system_prompt = f"""Eres un Asistente de Consultas experto en QA y TestLink.
            
            TU OBJETIVO:
            Ayudar al usuario a encontrar y consultar información existente en TestLink.
            Tu función es estrictamente de LECTURA y BÚSQUEDA.

            CONTEXTO ACTUAL DE TESTLINK (RAG):
            {json.dumps(context, indent=2)}
            
            INSTRUCCIONES:
            1. **CAPACIDADES**:
               - PUEDES buscar globalmente (`search_tests`).
               - PUEDES listar casos de una suite específica (`list_test_cases_in_suite`).
            2. **BÚSQUEDA**: Si el usuario pide buscar por palabras clave, usa `search_tests`.
            3. **SUITES**: Si el usuario pide "ver casos de la suite X", USA `list_test_cases_in_suite`.
               - ¡No digas que no puedes! La herramienta existe.
            4. **FORMATO**:
               - Si el usuario pide una TABLA, genera una tabla Markdown usando los datos del JSON de respuesta.
               - `search_tests` y `list_test_cases_in_suite` devuelven los datos necesarios seperados por comas.
            """
            
            # Configurar chat con herramientas
            chat = self.model.start_chat(enable_automatic_function_calling=False)
            
            # Enviar mensaje con prompt de sistema + usuario
            response = await chat.send_message_async(
                f"{system_prompt}\n\nUSER PROMPT: {prompt}",
                tools=tools,
                tool_config={'function_calling_config': {'mode': 'AUTO'}}
            )
            
            # Analizar respuesta para ver si hay llamadas a función
            part = response.parts[0]
            
            # 4. Ejecutar Acción (Tool Call)
            if part.function_call:
                fc = part.function_call
                function_name = fc.name
                arguments = dict(fc.args)
                
                logger.info(f"Agente ejecutando herramienta: {function_name} con args: {arguments}")
                
                # Ejecutar la herramienta
                tool_result = await self._execute_tool(function_name, arguments)
                
                # Enviar resultado al LLM para interpretación
                try:
                    function_response = content.FunctionResponse(
                        name=function_name,
                        response=tool_result
                    )
                    final_response = await chat.send_message_async(
                        [content.Part(function_response=function_response)]
                    )
                    return {
                        "success": True,
                        "action": function_name,
                        "message": final_response.text
                    }
                except Exception as e:
                    logger.error(f"Error en ciclo de respuesta LLM: {e}")
                    return tool_result
            else:
                return {
                    "success": True,
                    "action": "chat",
                    "message": part.text
                }
                
        except Exception as e:
            logger.error(f"Error del Agente: {str(e)}", exc_info=True)
            return {"success": False, "message": f"Error del Agente: {str(e)}"}

    async def _get_rag_context(self, prompt: str) -> Dict[str, Any]:
        """Recupera metadatos básicos para contexto"""
        context = {"projects": []}
        try:
            projects = self.tl_client.getProjects()
            if projects:
                for p in projects:
                    proj_info = {"id": p['id'], "name": p['name'], "prefix": p['prefix']}
                    if p['name'].lower() in prompt.lower():
                        # Si el proyecto es mencionado, traer más detalles
                        try:
                            plans = self.tl_client.getProjectTestPlans(p['id'])
                            if isinstance(plans, list):
                                proj_info["plans"] = [{"id": pl['id'], "name": pl['name']} for pl in plans]
                        except: pass
                    context["projects"].append(proj_info)
        except Exception as e:
            logger.warning(f"Advertencia RAG: {e}")
        return context
    
    async def _execute_tool(self, name: str, args: Dict) -> Dict:
        """Despachador de herramientas"""
        if name == "list_projects":
            return await self._list_projects()
        elif name == "read_test_case":
            return await self._read_test_case(args.get("test_case_external_id"), args.get("project_name"))
        elif name == "get_test_case_details":
            return await self._get_test_case_details(args.get("test_case_external_id"), args.get("project_name"))
        elif name == "list_test_suites":
            return await self._list_test_suites(args.get("project_name"))
        elif name == "list_test_plans":
            return await self._list_test_plans(args.get("project_name"))
        elif name == "list_builds":
            return await self._list_builds(args.get("plan_name"), args.get("project_name"))
        elif name == "read_test_execution":
            return await self._read_test_execution(args.get("test_case_external_id"), args.get("plan_name"), args.get("project_name"))
        elif name == "list_test_cases_in_suite":
            return await self._list_test_cases_in_suite(args.get("suite_name"), args.get("project_name"))
        elif name == "list_requirements":
            return await self._list_requirements(args.get("project_name"))
        elif name == "search_tests":
            return await self._search_tests(args.get("keyword"), args.get("project_name"))
        else:
            return {"success": False, "message": f"Acción desconocida: {name}"}
    
    # --- IMPLEMENTACIÓN DE MÉTODOS SOLICITADOS ---

    async def _list_projects(self) -> Dict[str, Any]:
        try:
            projects = self.tl_client.getProjects()
            # Limpiar datos sensibles
            if isinstance(projects, list):
                for p in projects:
                    if isinstance(p, dict): p.pop('api_key', None)
            return {"success": True, "data": projects, "message": f"Se encontraron {len(projects)} proyectos"}
        except Exception as e:
            return {"success": False, "message": f"Error listando proyectos: {str(e)}"}

    async def _read_test_case(self, test_case_external_id: str, project_name: str) -> Dict[str, Any]:
        try:
            result = self.tl_client.getTestCase(testcaseexternalid=test_case_external_id)
            if result:
                return {"success": True, "data": result, "message": f"Caso '{test_case_external_id}' recuperado"}
            return {"success": False, "message": "Caso de prueba no encontrado"}
        except Exception as e:
            return {"success": False, "message": f"Error leyendo caso: {str(e)}"}

    async def _get_test_case_details(self, test_case_external_id: str, project_name: str = None) -> Dict[str, Any]:
        try:
            # getTestCase suele devolver una lista de diccionarios
            result = self.tl_client.getTestCase(testcaseexternalid=test_case_external_id)
            
            if not result:
                return {"success": False, "message": "Caso de prueba no encontrado"}
            
            # Tomamos el primer elemento (versión activa/reciente)
            tc = result[0] if isinstance(result, list) and result else result
            
            if not isinstance(tc, dict):
                return {"success": False, "message": "Formato de respuesta inesperado de TestLink"}

            details = {
                "external_id": tc.get("full_tc_external_id", test_case_external_id),
                "name": tc.get("name"),
                "summary": tc.get("summary", "Sin resumen"),
                "preconditions": tc.get("preconditions", "Sin precondiciones"),
                "steps": tc.get("steps", []),
                "author": tc.get("author_login", "Desconocido"),
                "creation_ts": tc.get("creation_ts", "")
            }
            return {"success": True, "data": details, "message": f"Detalles recuperados para {test_case_external_id}"}
        except Exception as e:
            return {"success": False, "message": f"Error obteniendo detalles del caso: {str(e)}"}

    async def _list_test_suites(self, project_name: str) -> Dict[str, Any]:
        try:
            project_id = self._get_project_id_by_name(project_name)
            if not project_id: return {"success": False, "message": "Proyecto no encontrado"}
            
            suites = self.tl_client.getFirstLevelTestSuitesForTestProject(project_id)
            return {"success": True, "data": suites, "message": f"Se encontraron {len(suites) if isinstance(suites, list) else 0} suites"}
        except Exception as e:
            return {"success": False, "message": f"Error listando suites: {str(e)}"}

    async def _list_test_plans(self, project_name: str) -> Dict[str, Any]:
        try:
            project_id = self._get_project_id_by_name(project_name)
            if not project_id: return {"success": False, "message": "Proyecto no encontrado"}
            
            plans = self.tl_client.getProjectTestPlans(project_id)
            return {"success": True, "data": plans, "message": f"Se encontraron {len(plans) if isinstance(plans, list) else 0} planes"}
        except Exception as e:
             return {"success": False, "message": f"Error listando planes: {str(e)}"}

    async def _list_builds(self, plan_name: str, project_name: str) -> Dict[str, Any]:
        try:
            project_id = self._get_project_id_by_name(project_name)
            plan_id = self._get_plan_id_by_name(plan_name, project_id)
            if not plan_id: return {"success": False, "message": "Plan no encontrado"}
            
            builds = self.tl_client.getBuildsForTestPlan(plan_id)
            return {"success": True, "data": builds, "message": f"Se encontraron {len(builds) if isinstance(builds, list) else 0} builds"}
        except Exception as e:
             return {"success": False, "message": f"Error listando builds: {str(e)}"}

    async def _read_test_execution(self, test_case_external_id: str, plan_name: str, project_name: str) -> Dict[str, Any]:
        try:
            project_id = self._get_project_id_by_name(project_name)
            plan_id = self._get_plan_id_by_name(plan_name, project_id)
            
            result = self.tl_client.getLastExecutionResult(plan_id, testcaseexternalid=test_case_external_id)
            return {"success": True, "data": result, "message": "Resultado de ejecución recuperado"}
        except Exception as e:
             return {"success": False, "message": f"Error leyendo ejecución: {str(e)}"}

    async def _list_test_cases_in_suite(self, suite_name: str, project_name: str) -> Dict[str, Any]:
        try:
            logger.info(f'suite_name: {suite_name}')
            logger.info(f'project_name: {project_name}')

            project_id = self._get_project_id_by_name(project_name)
            if not project_id: 
                return {"success": False, "message": "Proyecto no encontrado"}
            
            suite_id = self._get_suite_id_by_name(suite_name, project_id)
            if not suite_id: 
                return {"success": False, "message": "Suite no encontrada"}
            
            # Usamos 'full' para obtener el autor (author_login)
            cases = self.tl_client.getTestCasesForTestSuite(suite_id, True, 'full')
            
            processed_cases = []
            # Manejar si devuelve dict o list
            iterator = cases.values() if isinstance(cases, dict) else cases
            
            if iterator:
                for c in iterator:
                    if isinstance(c, dict):
                        processed_cases.append({
                            "external_id": c.get('full_tc_external_id', c.get('id')),
                            "name": c.get('name'),
                            "author": c.get('author_login', 'Desconocido'),
                            "summary": c.get('summary', '')[:200]
                        })
            
            return {
                "success": True, 
                "data": processed_cases, 
                "message": f"Se encontraron {len(processed_cases)} casos en la suite"
            }
        except Exception as e:
            logger.info(f'_list_test_cases_in_suite: {str(e)}')
            return {"success": False, "message": f"Error listando casos de suite: {str(e)}"}

    async def _search_tests(self, keyword: str, project_name: str = None) -> Dict[str, Any]:
        try:
            all_cases = []
            projects = self.tl_client.getProjects()
            
            # Si se especifica un proyecto, buscar solo en ese proyecto
            if project_name:
                projects = [p for p in projects if p['name'].lower() == project_name.lower()]
                if not projects:
                    return {"success": False, "message": "Proyecto no encontrado"}
            
            for project in projects:
                try:
                    # Obtener todas las suites del proyecto
                    suites = self.tl_client.getFirstLevelTestSuitesForTestProject(project['id'])
                    if not suites:
                        continue
                        
                    for suite in suites:
                        try:
                            # Obtener casos de cada suite
                            cases = self.tl_client.getTestCasesForTestSuite(suite['id'], True, 'full')
                            if cases:
                                for case in cases:
                                    # Buscar keyword en nombre, resumen o pasos
                                    case_text = f"{case.get('name', '')} {case.get('summary', '')} {case.get('steps', '')}".lower()
                                    if keyword.lower() in case_text:
                                        case['project_name'] = project['name']
                                        case['suite_name'] = suite['name']
                                        all_cases.append(case)
                        except Exception as e:
                            logger.warning(f"Error procesando suite {suite.get('name', 'unknown')}: {e}")
                            continue
                except Exception as e:
                    logger.warning(f"Error procesando proyecto {project.get('name', 'unknown')}: {e}")
                    continue
            
            return {
                "success": True,
                "data": all_cases,
                "message": f"Se encontraron {len(all_cases)} casos que contienen '{keyword}'"
            }
        except Exception as e:
            return {"success": False, "message": f"Error buscando casos: {str(e)}"}

    async def _list_requirements(self, project_name: str) -> Dict[str, Any]:
        try:
            project_id = self._get_project_id_by_name(project_name)
            if not project_id:
                return {"success": False, "message": "Proyecto no encontrado"}
            
            specs = self.tl_client.getRequirementSpecifications(project_id)
            all_reqs = []
            if specs:
                for spec in specs:
                    reqs = self.tl_client.getRequirementsForRequirementSpecification(spec['id'], project_id)
                    if reqs:
                        all_reqs.extend(reqs)
            return {"success": True, "data": all_reqs, "message": f"Se encontraron {len(all_reqs)} requisitos"}
        except Exception as e:
             return {"success": False, "message": f"Error listando requisitos: {str(e)}"}

    # --- HELPERS ---
    def _get_project_id_by_name(self, name: str):
        projects = self.tl_client.getProjects()
        for p in projects:
            if p['name'].lower() == name.lower():
                return p['id']
        return None

    def _get_plan_id_by_name(self, plan_name: str, project_id):
        try:
            plans = self.tl_client.getProjectTestPlans(project_id)
            for p in plans:
                if p['name'].lower() == plan_name.lower():
                    return p['id']
        except: pass
        return None

    def _get_suite_id_by_name(self, suite_name: str, project_id):
        try:
            suites = self.tl_client.getFirstLevelTestSuitesForTestProject(project_id)
            for s in suites:
                if s['name'].lower() == suite_name.lower():
                    return s['id']
        except: pass
        return None

    def _get_tools_definition(self) -> List[Dict]:
        return [
            {
                "name": "list_projects",
                "description": "Get all test projects",
                "parameters": {"type": "OBJECT", "properties": {}}
            },
            {
                "name": "read_test_case",
                "description": "Fetch complete test case data",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "test_case_external_id": {"type": "STRING", "description": "External ID (e.g. PROJ-1)"},
                        "project_name": {"type": "STRING"}
                    },
                    "required": ["test_case_external_id"]
                }
            },
            {
                "name": "get_test_case_details",
                "description": "Get detailed info (summary, preconditions, steps) of a test case",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "test_case_external_id": {"type": "STRING", "description": "External ID (e.g. PROJ-1)"},
                        "project_name": {"type": "STRING"}
                    },
                    "required": ["test_case_external_id"]
                }
            },
            {
                "name": "list_test_suites",
                "description": "Get test suites for a project",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"project_name": {"type": "STRING"}},
                    "required": ["project_name"]
                }
            },
            {
                "name": "list_test_plans",
                "description": "List all test plans for a project",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"project_name": {"type": "STRING"}},
                    "required": ["project_name"]
                }
            },
            {
                "name": "list_builds",
                "description": "List all builds for a test plan",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "plan_name": {"type": "STRING"},
                        "project_name": {"type": "STRING"}
                    },
                    "required": ["plan_name", "project_name"]
                }
            },
            {
                "name": "read_test_execution",
                "description": "Get test execution details",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "test_case_external_id": {"type": "STRING"},
                        "plan_name": {"type": "STRING"},
                        "project_name": {"type": "STRING"}
                    },
                    "required": ["test_case_external_id", "plan_name", "project_name"]
                }
            },
            {
                "name": "list_test_cases_in_suite",
                "description": "Get all test cases in a specific test suite",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "suite_name": {"type": "STRING"},
                        "project_name": {"type": "STRING"}
                    },
                    "required": ["suite_name", "project_name"]
                }
            },
            {
                "name": "list_requirements",
                "description": "Get all requirements for a project",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"project_name": {"type": "STRING"}},
                    "required": ["project_name"]
                }
            },
            {
                "name": "search_tests",
                "description": "Search test cases by keyword in name, summary or steps",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "keyword": {"type": "STRING", "description": "Keyword to search for"},
                        "project_name": {"type": "STRING", "description": "Optional: limit search to specific project"}
                    },
                    "required": ["keyword"]
                }
            }
        ]

# Instancia global del cliente MCP
mcp_client = TestLinkMCPClient()

@app.post("/testlink/prompt")
async def process_testlink_prompt(request: PromptRequest):
    """
    Procesa un prompt en lenguaje natural y ejecuta acciones en TestLink
    """
    try:
        load_dotenv(override=True)
        testlink_url = os.getenv("TESTLINK_URL")
        api_key = os.getenv("TESTLINK_API_KEY")
        
        connected = await mcp_client.connect(testlink_url, api_key)
        if not connected:
            raise HTTPException(status_code=500, detail=f"No se pudo conectar a TestLink en {testlink_url}")
        
        result = await mcp_client.process_prompt(request.prompt)
        
        message = result.get("message", "")
        if not isinstance(message, str):
            message = str(message)
            
        return {"message": message}
    except Exception as e:
        logger.error(f"Error crítico en endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.get("/testlink/health")
async def health_check():
    return {"status": "healthy", "service": "TestLink MCP API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "testlink_api:app",
        host=os.getenv("API_HOST", "0.0.0.0"), 
        port=int(os.getenv("API_PORT", 8012)),
        log_level=os.getenv("LOG_LEVEL", "info"),
        reload=False
    )