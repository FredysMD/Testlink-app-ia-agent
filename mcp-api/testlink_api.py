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

class TestLinkResponse(BaseModel):
    success: bool
    message: str
    action_taken: Optional[str] = None
    data: Optional[Any] = None

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
            logger.debug(f"Usando API key: {api_key[:5]}...{api_key[-5:] if len(api_key)>10 else ''}")
            self.tl_client = testlink.TestlinkAPIClient(url, api_key)
            # Test connection with a simple call
            try:
                about_info = self.tl_client.about()
                logger.info(f"Conexión exitosa a TestLink: {about_info}")
                return True
            except Exception as api_error:
                logger.error(f"Fallo en llamada API inicial: {api_error}")
                # If about() fails, it might be an API key issue
                # Let's try to at least verify the server is reachable
                import urllib.request
                try:
                    response = urllib.request.urlopen(url.replace('/lib/api/xmlrpc/v1/xmlrpc.php', '/login.php'))
                    if response.getcode() == 200:
                        logger.warning("Servidor TestLink accesible, pero la API Key podría ser inválida")
                        return False
                except:
                    logger.error("Servidor TestLink no es accesible")
                    return False
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
            system_prompt = f"""Eres un Strand Agent experto en QA y TestLink, capaz de gestionar todo el ciclo de vida de pruebas.
            
            TU OBJETIVO:
            Ayudar al usuario a planificar, diseñar y ejecutar pruebas de software, asegurando la integridad de los datos en TestLink.

            CONOCIMIENTO DEL DOMINIO:
            1. Jerarquía: Proyecto -> Test Plan -> Build.
            2. Diseño: Proyecto -> Test Suite -> Test Case.
            3. Ejecución: Para reportar un resultado, el caso debe estar añadido a un Test Plan y debe existir un Build activo.
            
            CONTEXTO ACTUAL DE TESTLINK (RAG):
            {json.dumps(context, indent=2)}
            
            INSTRUCCIONES:
            1. ANÁLISIS: Antes de actuar, verifica si tienes todos los IDs o nombres necesarios (Proyecto, Plan, Build).
            2. RAG: Usa el contexto proporcionado para resolver nombres a IDs automáticamente sin preguntar al usuario si es posible.
            3. HERRAMIENTAS: Usa las funciones disponibles para realizar acciones. Si una acción compleja requiere pasos previos (ej: reportar resultado requiere plan), verifica o crea los prerrequisitos o guía al usuario.
            4. IDIOMA: Responde siempre en español profesional y conciso.
            5. FORMATO: Si listas datos, usa viñetas o tablas markdown.
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
                return await self._execute_tool(function_name, arguments)
            else:
                # Respuesta conversacional
                return {
                    "success": True,
                    "action": "chat",
                    "message": part.text
                }
                
        except Exception as e:
            logger.error(f"Error del Agente: {str(e)}", exc_info=True)
            return {
                "success": False,
                "message": f"Error del Agente: {str(e)}"
            }

    async def _get_rag_context(self, prompt: str) -> Dict[str, Any]:
        """Recupera metadatos de TestLink para dar contexto al LLM"""
        context = {"projects": []}
        try:
            # Obtener lista básica de proyectos
            projects = self.tl_client.getProjects()
            if projects:
                for p in projects:
                    proj_info = {"id": p['id'], "name": p['name'], "prefix": p['prefix']}
                    
                    # Si el prompt menciona este proyecto, traer sus suites (Deep Retrieval)
                    if p['name'].lower() in prompt.lower():
                        suites = self.tl_client.getFirstLevelTestSuitesForTestProject(p['id'])
                        if suites and isinstance(suites, list):
                            proj_info["suites"] = [{"id": s['id'], "name": s['name']} for s in suites]
                        
                        # Intentar obtener planes de prueba también
                        try:
                            plans = self.tl_client.getProjectTestPlans(p['id'])
                            if plans and isinstance(plans, list):
                                proj_info["plans"] = [{"id": pl['id'], "name": pl['name']} for pl in plans]
                        except:
                            pass
                    
                    context["projects"].append(proj_info)
        except Exception as e:
            logger.warning(f"Advertencia RAG (recuperación de contexto): {e}")
        return context
    
    async def _execute_tool(self, name: str, args: Dict) -> Dict:
        """Despachador de herramientas"""
        if name == "create_project":
            return await self._create_project(args["name"], args.get("prefix"))
        elif name == "list_projects":
            return await self._list_projects()
        
        # Test Case Management
        elif name == "read_test_case":
            return await self._read_test_case(args.get("test_case_external_id"), args.get("project_name"))
        elif name == "create_test_case":
            return await self._create_test_case(args["name"], args.get("project_name"), args.get("suite_name"), args.get("summary"))
        elif name == "update_test_case":
            return await self._update_test_case(args.get("test_case_external_id"), args.get("project_name"), args)
        elif name == "delete_test_case":
            return await self._delete_test_case(args.get("test_case_external_id"), args.get("project_name"))
            
        # Test Suite Management
        elif name == "list_test_suites":
            return await self._list_test_suites(args.get("project_name"))
        elif name == "list_test_cases_in_suite":
            return await self._list_test_cases_in_suite(args.get("suite_name"), args.get("project_name"))
        elif name == "create_test_suite":
            return await self._create_test_suite(args["name"], args.get("project_name"))
        elif name == "update_test_suite":
            return await self._update_test_suite(args.get("suite_name"), args.get("project_name"), args)
            
        # Search
        elif name == "search_tests":
            return await self._search_tests(args.get("keywords", []))
            
        # Test Plan Management
        elif name == "list_test_plans":
            return await self._list_test_plans(args.get("project_name"))
        elif name == "create_test_plan":
            return await self._create_test_plan(args["name"], args["project_name"], args.get("notes", ""))
        elif name == "delete_test_plan":
            return await self._delete_test_plan(args.get("plan_name"), args.get("project_name"))
        elif name == "get_test_cases_for_test_plan":
            return await self._get_test_cases_for_test_plan(args.get("plan_name"), args.get("project_name"))
        elif name == "add_test_case_to_test_plan":
            return await self._add_test_case_to_plan(args["case_name"], args["plan_name"], args["project_name"])
            
        # Build Management
        elif name == "list_builds":
            return await self._list_builds(args.get("plan_name"), args.get("project_name"))
        elif name == "create_build":
            return await self._create_build(args["name"], args["plan_name"], args["project_name"], args.get("notes", ""))
        elif name == "close_build":
            return await self._close_build(args.get("build_name"), args.get("plan_name"), args.get("project_name"))
            
        # Test Execution Management
        elif name == "read_test_execution":
            return await self._read_test_execution(args.get("test_case_external_id"), args.get("plan_name"), args.get("project_name"))
        elif name == "create_test_execution":
            return await self._report_test_result(args["case_name"], args["status"], args["plan_name"], args["build_name"], args["project_name"], args.get("notes", ""))
            
        # Requirement Management
        elif name == "list_requirements":
            return await self._list_requirements(args.get("project_name"))
        elif name == "get_requirement":
            return await self._get_requirement(args.get("req_doc_id"), args.get("project_name"))
            
        else:
            return {"success": False, "message": f"Herramienta desconocida: {name}"}
    
    # --- IMPLEMENTACIÓN DE HERRAMIENTAS (TOOLS) ---

    async def _create_project(self, name: str, prefix: str = None) -> Dict[str, Any]:
        if not prefix:
            prefix = "".join([w[0].upper() for w in name.split()[:3]])
        try:
            result = self.tl_client.createTestProject(name, prefix)
            return {
                "action": "create_project",
                "success": True,
                "data": result,
                "message": f"Proyecto '{name}' creado exitosamente con prefijo '{prefix}'"
            }
        except Exception as e:
            return {"success": False, "message": f"Error creando proyecto: {str(e)}"}

    async def _list_projects(self) -> Dict[str, Any]:
        try:
            projects = self.tl_client.getProjects()
            return {
                "action": "list_projects",
                "success": True,
                "data": projects,
                "message": f"Se encontraron {len(projects)} proyectos"
            }
        except Exception as e:
            return {
                "action": "list_projects",
                "success": False,
                "message": f"Error listando proyectos: {str(e)}"
            }
    
    async def _create_test_case(self, name: str, project_name: str = None, suite_name: str = None, summary: str = "") -> Dict[str, Any]:
        try:
            projects = self.tl_client.getProjects()
            if not projects:
                return {"success": False, "message": "No hay proyectos disponibles."}
            
            # Resolver Project ID
            project_id = None
            if project_name:
                for p in projects:
                    if p['name'].lower() == project_name.lower():
                        project_id = p['id']
                        break
            if not project_id:
                project_id = projects[0]['id'] # Fallback al primero

            # Resolver Suite ID
            suites = self.tl_client.getFirstLevelTestSuitesForTestProject(project_id)
            if not suites:
                return {"success": False, "message": "El proyecto no tiene suites. Crea una primero."}
                
            suite_id = None
            if suite_name:
                for s in suites:
                    if s['name'].lower() == suite_name.lower():
                        suite_id = s['id']
                        break
            if not suite_id:
                suite_id = suites[0]['id'] # Fallback a la primera

            result = self.tl_client.createTestCase(
                name,
                suite_id,
                project_id,
                "admin",
                summary or f"Caso de prueba: {name}"
            )
            return {
                "action": "create_test_case",
                "success": True,
                "data": result,
                "message": f"Caso '{name}' creado exitosamente en proyecto {project_id}"
            }
        except Exception as e:
            return {"success": False, "message": f"Error creando caso: {str(e)}"}
    
    async def _list_test_cases(self, project_name: str = None) -> Dict[str, Any]:
        try:
            projects = self.tl_client.getProjects()
            all_cases = []
            
            for project in projects:
                if project_name and project['name'].lower() != project_name.lower():
                    continue
                    
                project_id = project['id']
                project_name = project['name']
                
                try:
                    suites = self.tl_client.getFirstLevelTestSuitesForTestProject(project_id)
                    for suite in suites:
                        suite_name = suite.get('name', '')
                        try:
                            cases = self.tl_client.getTestCasesForTestSuite(suite['id'], deep=True)
                            for case in cases:
                                all_cases.append({
                                    "id": case.get('id'),
                                    "name": case.get('name', ''),
                                    "summary": case.get('summary', '')[:100] + "..." if len(case.get('summary', '')) > 100 else case.get('summary', ''),
                                    "project": project_name,
                                    "suite": suite_name
                                })
                        except:
                            pass
                except:
                    pass
            
            return {
                "action": "list_test_cases",
                "success": True,
                "data": {
                    "cases": all_cases,
                    "total_count": len(all_cases)
                },
                "message": f"Se encontraron {len(all_cases)} casos de prueba en total"
            }
            
        except Exception as e:
            return {
                "action": "list_test_cases",
                "success": False,
                "message": f"Error listando casos: {str(e)}"
            }
    
    async def _create_test_suite(self, name: str, project_name: str = None) -> Dict[str, Any]:
        try:
            projects = self.tl_client.getProjects()
            if not projects:
                return {"success": False, "message": "No hay proyectos disponibles"}
                
            project_id = projects[0]['id']
            if project_name:
                for p in projects:
                    if p['name'].lower() == project_name.lower():
                        project_id = p['id']
                        break
                        
            result = self.tl_client.createTestSuite(project_id, name, f"Suite: {name}")
            return {
                "action": "create_test_suite",
                "success": True,
                "data": result,
                "message": f"Suite '{name}' creada exitosamente"
            }
        except Exception as e:
            return {"success": False, "message": f"Error creando suite: {str(e)}"}
    
    # --- NUEVAS HERRAMIENTAS DE GESTIÓN (CASOS, SUITES, ETC) ---

    async def _read_test_case(self, test_case_external_id: str, project_name: str) -> Dict[str, Any]:
        try:
            # getTestCase acepta 'testcaseexternalid' (ej: PROJ-1)
            result = self.tl_client.getTestCase(testcaseexternalid=test_case_external_id)
            if result:
                return {"success": True, "data": result, "action": "read_test_case"}
            return {"success": False, "message": "Caso de prueba no encontrado"}
        except Exception as e:
            return {"success": False, "message": f"Error leyendo caso: {str(e)}"}

    async def _update_test_case(self, test_case_external_id: str, project_name: str, updates: Dict) -> Dict[str, Any]:
        try:
            # Extraer campos de actualización
            title = updates.get("title")
            summary = updates.get("summary")
            preconditions = updates.get("preconditions")
            steps = updates.get("steps")
            expected_results = updates.get("expected_results")
            
            result = self.tl_client.updateTestCase(
                testcaseexternalid=test_case_external_id,
                title=title,
                summary=summary,
                preconditions=preconditions,
                steps=steps,
                expected_results=expected_results
            )
            return {"success": True, "data": result, "action": "update_test_case"}
        except Exception as e:
            return {"success": False, "message": f"Error actualizando caso: {str(e)}"}

    async def _delete_test_case(self, test_case_external_id: str, project_name: str) -> Dict[str, Any]:
        try:
            # TestLink API a veces no expone deleteTestCase directamente o requiere ID interno
            # Intentaremos desactivarlo (active=0) que es la práctica común segura
            self.tl_client.updateTestCase(testcaseexternalid=test_case_external_id, active=0)
            return {"success": True, "message": f"Caso {test_case_external_id} desactivado/eliminado", "action": "delete_test_case"}
        except Exception as e:
             return {"success": False, "message": f"Error eliminando caso: {str(e)}"}

    async def _list_test_suites(self, project_name: str) -> Dict[str, Any]:
        try:
            project_id = self._get_project_id_by_name(project_name)
            if not project_id: return {"success": False, "message": "Proyecto no encontrado"}
            
            suites = self.tl_client.getFirstLevelTestSuitesForTestProject(project_id)
            return {"success": True, "data": suites, "action": "list_test_suites"}
        except Exception as e:
            return {"success": False, "message": f"Error listando suites: {str(e)}"}

    async def _list_test_cases_in_suite(self, suite_name: str, project_name: str) -> Dict[str, Any]:
        try:
            project_id = self._get_project_id_by_name(project_name)
            if not project_id: return {"success": False, "message": "Proyecto no encontrado"}
            
            suite_id = self._get_suite_id_by_name(suite_name, project_id)
            if not suite_id: return {"success": False, "message": "Suite no encontrada"}
            
            cases = self.tl_client.getTestCasesForTestSuite(suite_id, deep=True, details='simple')
            return {"success": True, "data": cases, "action": "list_test_cases_in_suite"}
        except Exception as e:
            return {"success": False, "message": f"Error listando casos de suite: {str(e)}"}

    async def _update_test_suite(self, suite_name: str, project_name: str, updates: Dict) -> Dict[str, Any]:
        try:
            project_id = self._get_project_id_by_name(project_name)
            if not project_id: return {"success": False, "message": "Proyecto no encontrado"}
            
            suite_id = self._get_suite_id_by_name(suite_name, project_id)
            if not suite_id: return {"success": False, "message": "Suite no encontrada"}
            
            new_name = updates.get("new_name", suite_name)
            details = updates.get("details")
            
            self.tl_client.updateTestSuite(suite_id, project_id, new_name, details)
            return {"success": True, "message": "Suite actualizada", "action": "update_test_suite"}
        except Exception as e:
             return {"success": False, "message": f"Error actualizando suite: {str(e)}"}

    # --- NUEVAS HERRAMIENTAS DE CICLO DE VIDA (PLAN, BUILD, EXECUTION) ---

    async def _list_test_plans(self, project_name: str) -> Dict[str, Any]:
        try:
            project_id = self._get_project_id_by_name(project_name)
            if not project_id: return {"success": False, "message": "Proyecto no encontrado"}
            
            plans = self.tl_client.getProjectTestPlans(project_id)
            return {"success": True, "data": plans, "action": "list_test_plans"}
        except Exception as e:
             return {"success": False, "message": f"Error listando planes: {str(e)}"}

    async def _create_test_plan(self, name: str, project_name: str, notes: str = "") -> Dict[str, Any]:
        try:
            # createTestPlan usa nombre de proyecto, no ID
            result = self.tl_client.createTestPlan(name, project_name, notes=notes, active=1, public=1)
            return {
                "action": "create_test_plan",
                "success": True,
                "data": result,
                "message": f"Plan de pruebas '{name}' creado en proyecto '{project_name}'"
            }
        except Exception as e:
            return {"success": False, "message": f"Error creando plan: {str(e)}"}

    async def _delete_test_plan(self, plan_name: str, project_name: str) -> Dict[str, Any]:
        try:
            project_id = self._get_project_id_by_name(project_name)
            if not project_id: return {"success": False, "message": "Proyecto no encontrado"}
            
            plan_id = self._get_plan_id_by_name(plan_name, project_id)
            if not plan_id: return {"success": False, "message": "Plan no encontrado"}
            
            # Intentar borrar usando método raw si el cliente no lo expone directamente
            try:
                self.tl_client.server.tl.deleteTestPlan(self.tl_client.devKey, plan_id)
                return {"success": True, "message": "Plan eliminado", "action": "delete_test_plan"}
            except:
                return {"success": False, "message": "No se pudo eliminar el plan (posible restricción de API)"}
        except Exception as e:
             return {"success": False, "message": f"Error eliminando plan: {str(e)}"}

    async def _get_test_cases_for_test_plan(self, plan_name: str, project_name: str) -> Dict[str, Any]:
        try:
            project_id = self._get_project_id_by_name(project_name)
            plan_id = self._get_plan_id_by_name(plan_name, project_id)
            if not plan_id: return {"success": False, "message": "Plan no encontrado"}
            
            cases = self.tl_client.getTestCasesForTestPlan(plan_id)
            return {"success": True, "data": cases, "action": "get_test_cases_for_test_plan"}
        except Exception as e:
             return {"success": False, "message": f"Error obteniendo casos del plan: {str(e)}"}

    async def _list_builds(self, plan_name: str, project_name: str) -> Dict[str, Any]:
        try:
            project_id = self._get_project_id_by_name(project_name)
            plan_id = self._get_plan_id_by_name(plan_name, project_id)
            if not plan_id: return {"success": False, "message": "Plan no encontrado"}
            
            builds = self.tl_client.getBuildsForTestPlan(plan_id)
            return {"success": True, "data": builds, "action": "list_builds"}
        except Exception as e:
             return {"success": False, "message": f"Error listando builds: {str(e)}"}

    async def _create_build(self, name: str, plan_name: str, project_name: str, notes: str = "") -> Dict[str, Any]:
        try:
            project_id = self._get_project_id_by_name(project_name)
            if not project_id:
                return {"success": False, "message": f"Proyecto '{project_name}' no encontrado"}
            
            plan_id = self._get_plan_id_by_name(plan_name, project_id)
            if not plan_id:
                return {"success": False, "message": f"Plan '{plan_name}' no encontrado en proyecto '{project_name}'"}

            result = self.tl_client.createBuild(plan_id, name, buildnotes=notes)
            return {
                "action": "create_build",
                "success": True,
                "data": result,
                "message": f"Build '{name}' creado en plan '{plan_name}'"
            }
        except Exception as e:
            return {"success": False, "message": f"Error creando build: {str(e)}"}

    async def _close_build(self, build_name: str, plan_name: str, project_name: str) -> Dict[str, Any]:
        # La API XMLRPC estándar de TestLink no siempre expone 'closeBuild' fácilmente.
        # Esta es una implementación tentativa.
        return {"success": False, "message": "Función close_build no soportada completamente por la versión actual de la API"}

    async def _add_test_case_to_plan(self, case_name: str, plan_name: str, project_name: str) -> Dict[str, Any]:
        try:
            project_id = self._get_project_id_by_name(project_name)
            if not project_id: return {"success": False, "message": "Proyecto no encontrado"}
            
            plan_id = self._get_plan_id_by_name(plan_name, project_id)
            if not plan_id: return {"success": False, "message": "Plan no encontrado"}

            # Buscar ID del caso (necesitamos el ID externo completo ej: PROJ-123)
            # Esta es una simplificación, idealmente buscaríamos por ID exacto
            case_info = self._find_case_by_name(case_name, project_id)
            if not case_info:
                return {"success": False, "message": f"Caso '{case_name}' no encontrado"}
            
            # full_external_id suele ser necesario
            full_ext_id = case_info.get('full_tc_external_id') or f"{self._get_project_prefix(project_id)}-{case_info['tc_external_id']}"

            result = self.tl_client.addTestCaseToTestPlan(project_id, plan_id, full_ext_id, version=1)
            return {
                "action": "add_test_case_to_plan",
                "success": True,
                "data": result,
                "message": f"Caso '{case_name}' ({full_ext_id}) añadido al plan '{plan_name}'"
            }
        except Exception as e:
            return {"success": False, "message": f"Error añadiendo caso al plan: {str(e)}"}

    async def _read_test_execution(self, test_case_external_id: str, plan_name: str, project_name: str) -> Dict[str, Any]:
        try:
            project_id = self._get_project_id_by_name(project_name)
            plan_id = self._get_plan_id_by_name(plan_name, project_id)
            
            result = self.tl_client.getLastExecutionResult(plan_id, testcaseexternalid=test_case_external_id)
            return {"success": True, "data": result, "action": "read_test_execution"}
        except Exception as e:
             return {"success": False, "message": f"Error leyendo ejecución: {str(e)}"}

    async def _report_test_result(self, case_name: str, status: str, plan_name: str, build_name: str, project_name: str, notes: str = "") -> Dict[str, Any]:
        try:
            # Mapeo de status
            status_map = {'pass': 'p', 'fail': 'f', 'blocked': 'b', 'p': 'p', 'f': 'f', 'b': 'b'}
            status_code = status_map.get(status.lower())
            if not status_code:
                return {"success": False, "message": "Estado inválido. Usar: pass, fail, blocked"}

            project_id = self._get_project_id_by_name(project_name)
            if not project_id: return {"success": False, "message": "Proyecto no encontrado"}
            
            plan_id = self._get_plan_id_by_name(plan_name, project_id)
            if not plan_id: return {"success": False, "message": "Plan no encontrado"}

            case_info = self._find_case_by_name(case_name, project_id)
            if not case_info: return {"success": False, "message": f"Caso '{case_name}' no encontrado"}

            # Reportar resultado
            result = self.tl_client.reportTCResult(
                case_info['id'], # Internal ID
                plan_id,
                build_name,
                status_code,
                notes,
                guess=True # Permite cierta flexibilidad
            )
            return {
                "action": "report_test_result",
                "success": True,
                "data": result,
                "message": f"Resultado '{status}' reportado para caso '{case_name}' en build '{build_name}'"
            }
        except Exception as e:
            return {"success": False, "message": f"Error reportando resultado: {str(e)}"}

    # --- REQUIREMENTS ---
    async def _list_requirements(self, project_name: str) -> Dict[str, Any]:
        try:
            project_id = self._get_project_id_by_name(project_name)
            # Obtener especificaciones primero
            specs = self.tl_client.getRequirementSpecifications(project_id)
            all_reqs = []
            if specs:
                for spec in specs:
                    reqs = self.tl_client.getRequirementsForRequirementSpecification(spec['id'], project_id)
                    all_reqs.extend(reqs)
            return {"success": True, "data": all_reqs, "action": "list_requirements"}
        except Exception as e:
             return {"success": False, "message": f"Error listando requisitos: {str(e)}"}

    async def _get_requirement(self, req_doc_id: str, project_name: str) -> Dict[str, Any]:
        try:
            project_id = self._get_project_id_by_name(project_name)
            result = self.tl_client.getRequirement(req_doc_id, project_id)
            return {"success": True, "data": result, "action": "get_requirement"}
        except Exception as e:
             return {"success": False, "message": f"Error obteniendo requisito: {str(e)}"}

    # --- HELPERS ---
    def _get_project_id_by_name(self, name: str):
        projects = self.tl_client.getProjects()
        for p in projects:
            if p['name'].lower() == name.lower():
                return p['id']
        return None

    def _get_project_prefix(self, project_id):
        projects = self.tl_client.getProjects()
        for p in projects:
            if p['id'] == project_id:
                return p['prefix']
        return ""

    def _get_plan_id_by_name(self, name: str, project_id):
        try:
            plans = self.tl_client.getProjectTestPlans(project_id)
            for p in plans:
                if p['name'].lower() == name.lower():
                    return p['id']
        except:
            pass
        return None

    def _get_suite_id_by_name(self, suite_name: str, project_id):
        try:
            suites = self.tl_client.getFirstLevelTestSuitesForTestProject(project_id)
            for s in suites:
                if s['name'].lower() == suite_name.lower():
                    return s['id']
        except:
            pass
        return None

    def _find_case_by_name(self, name: str, project_id):
        # Intentar búsqueda por ID externo si tiene formato (ej: PROJ-123)
        if '-' in name:
            try:
                case = self.tl_client.getTestCase(testcaseexternalid=name)
                if case and isinstance(case, list): case = case[0]
                if case: return case
            except:
                pass
        
        # Búsqueda por nombre en suites de primer nivel
        try:
            suites = self.tl_client.getFirstLevelTestSuitesForTestProject(project_id)
            for s in suites:
                cases = self.tl_client.getTestCasesForTestSuite(s['id'], deep=True, details='full')
                for c in cases:
                    if c['name'].lower() == name.lower() or name in c.get('summary', ''):
                        return c
        except:
            pass
        return None

    async def _search_tests(self, search_terms: List[str]) -> Dict[str, Any]:
        """Busca casos de prueba basado en palabras clave (Tool)"""
        try:
            if not search_terms:
                return {"success": False, "message": "No se proporcionaron términos de búsqueda"}
            
            # Obtener todos los proyectos
            projects = self.tl_client.getProjects()
            results = []
            
            for project in projects:
                project_id = project['id']
                project_name = project['name']
                
                # Buscar en el nombre del proyecto (búsqueda parcial)
                if any(term.lower() in project_name.lower() for term in search_terms):
                    results.append({
                        "type": "project",
                        "name": project_name,
                        "id": project_id,
                        "match_reason": "Nombre del proyecto coincide"
                    })
                
                # Buscar por prefijo también
                project_prefix = project.get('prefix', '')
                if any(term.lower() in project_prefix.lower() for term in search_terms):
                    results.append({
                        "type": "project", 
                        "name": project_name,
                        "id": project_id,
                        "match_reason": "Prefijo del proyecto coincide"
                    })
                
                # Obtener suites del proyecto
                try:
                    suites = self.tl_client.getFirstLevelTestSuitesForTestProject(project_id)
                    for suite in suites:
                        suite_name = suite.get('name', '')
                        # Búsqueda inteligente para términos como "auth"
                        suite_lower = suite_name.lower()
                        matches = False
                        
                        for term in search_terms:
                            term_lower = term.lower()
                            
                            # Coincidencia exacta
                            if term_lower in suite_lower:
                                matches = True
                                break
                            
                            # Coincidencia por palabras que empiecen con el término
                            if any(word.startswith(term_lower) for word in suite_lower.split()):
                                matches = True
                                break
                            
                            # Casos especiales para abreviaciones comunes
                            if term_lower == 'auth':
                                auth_words = ['autenticación', 'authentication', 'autorization', 'autorización']
                                if any(auth_word in suite_lower for auth_word in auth_words):
                                    matches = True
                                    break
                        
                        if matches:
                            results.append({
                                "type": "test_suite",
                                "name": suite_name,
                                "project": project_name,
                                "id": suite.get('id'),
                                "match_reason": "Nombre de suite coincide"
                            })
                            
                            # Buscar casos de prueba en la suite
                            try:
                                test_cases = self.tl_client.getTestCasesForTestSuite(suite['id'])
                                for case in test_cases:
                                    case_name = case.get('name', '')
                                    case_summary = case.get('summary', '')
                                    
                                    if any(term.lower() in case_name.lower() or term.lower() in case_summary.lower() for term in search_terms):
                                        results.append({
                                            "type": "test_case",
                                            "name": case_name,
                                            "summary": case_summary[:200] + "..." if len(case_summary) > 200 else case_summary,
                                            "project": project_name,
                                            "suite": suite_name,
                                            "id": case.get('id'),
                                            "match_reason": "Contenido del caso coincide"
                                        })
                            except:
                                pass
                except:
                    pass
            
            if results:
                return {
                    "action": "search_tests",
                    "success": True,
                    "data": {
                        "search_terms": search_terms,
                        "results": results,
                        "total_found": len(results)
                    },
                    "message": f"Se encontraron {len(results)} elementos relacionados con: {', '.join(search_terms)}"
                }
            else:
                return {
                    "action": "search_tests",
                    "success": True,
                    "data": {"search_terms": search_terms, "results": [], "total_found": 0},
                    "message": f"No se encontraron elementos relacionados con: {', '.join(search_terms)}"
                }
                
        except Exception as e:
            return {
                "action": "search_tests",
                "success": False,
                "message": f"Error en la búsqueda: {str(e)}"
            }
    
    def _get_tools_definition(self) -> List[Dict]:
        """Define las herramientas disponibles para el Agente"""
        return [
            # Project Management
            {
                "name": "create_project",
                "description": "Create a new project",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "name": {"type": "STRING", "description": "Nombre del proyecto"},
                        "prefix": {"type": "STRING", "description": "Prefijo corto para el proyecto (ej: PROJ)"}
                    },
                    "required": ["name"]
                }
            },
            {
                "name": "list_projects",
                "description": "Get all test projects",
                "parameters": {"type": "OBJECT", "properties": {}}
            },
            # Test Case Management
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
                "name": "create_test_case",
                "description": "Create new test case with validation",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "name": {"type": "STRING", "description": "Nombre del caso de prueba"},
                        "project_name": {"type": "STRING", "description": "Nombre del proyecto donde crear el caso"},
                        "suite_name": {"type": "STRING", "description": "Nombre de la suite donde crear el caso"},
                        "summary": {"type": "STRING", "description": "Descripción o resumen del caso"}
                    },
                    "required": ["name"]
                }
            },
            {
                "name": "update_test_case",
                "description": "Update test case fields with full validation",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "test_case_external_id": {"type": "STRING"},
                        "project_name": {"type": "STRING"},
                        "title": {"type": "STRING"},
                        "summary": {"type": "STRING"},
                        "preconditions": {"type": "STRING"},
                        "steps": {"type": "ARRAY", "items": {"type": "OBJECT"}},
                        "expected_results": {"type": "STRING"}
                    },
                    "required": ["test_case_external_id"]
                }
            },
            {
                "name": "delete_test_case",
                "description": "Remove test case permanently",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "test_case_external_id": {"type": "STRING"},
                        "project_name": {"type": "STRING"}
                    },
                    "required": ["test_case_external_id"]
                }
            },
            # Test Suite Management
            {
                "name": "list_test_suites",
                "description": "Get test suites for a project",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "project_name": {"type": "STRING"}
                    },
                    "required": ["project_name"]
                }
            },
            {
                "name": "list_test_cases_in_suite",
                "description": "Get all test cases in a suite",
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
                "name": "create_test_suite",
                "description": "Create a new test suite in a project",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "name": {"type": "STRING"},
                        "project_name": {"type": "STRING"}
                    },
                    "required": ["name", "project_name"]
                }
            },
            {
                "name": "update_test_suite",
                "description": "Update test suite properties",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "suite_name": {"type": "STRING"},
                        "project_name": {"type": "STRING"},
                        "new_name": {"type": "STRING"},
                        "details": {"type": "STRING"}
                    },
                    "required": ["suite_name", "project_name"]
                }
            },
            # Test Plan Management
            {
                "name": "list_test_plans",
                "description": "List all test plans for a project",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "project_name": {"type": "STRING"}
                    },
                    "required": ["project_name"]
                }
            },
            {
                "name": "create_test_plan",
                "description": "Create a new test plan",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "name": {"type": "STRING", "description": "Nombre del plan de pruebas"},
                        "project_name": {"type": "STRING", "description": "Nombre del proyecto"},
                        "notes": {"type": "STRING", "description": "Notas o descripción del plan"}
                    },
                    "required": ["name", "project_name"]
                }
            },
            {
                "name": "delete_test_plan",
                "description": "Delete a test plan",
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
                "name": "get_test_cases_for_test_plan",
                "description": "List all test cases in a test plan",
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
                "name": "add_test_case_to_test_plan",
                "description": "Add a test case to a test plan",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "case_name": {"type": "STRING", "description": "Name or External ID"},
                        "plan_name": {"type": "STRING"},
                        "project_name": {"type": "STRING"}
                    },
                    "required": ["case_name", "plan_name", "project_name"]
                }
            },
            # Build Management
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
                "name": "create_build",
                "description": "Create a new build",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "name": {"type": "STRING", "description": "Nombre del Build (ej: 1.0.0)"},
                        "plan_name": {"type": "STRING", "description": "Nombre del plan de pruebas"},
                        "project_name": {"type": "STRING", "description": "Nombre del proyecto"},
                        "notes": {"type": "STRING", "description": "Notas del build"}
                    },
                    "required": ["name", "plan_name", "project_name"]
                }
            },
            {
                "name": "close_build",
                "description": "Close a build (prevents new test executions)",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "build_name": {"type": "STRING"},
                        "plan_name": {"type": "STRING"},
                        "project_name": {"type": "STRING", "description": "Nombre del proyecto"}
                    },
                    "required": ["build_name", "plan_name", "project_name"]
                }
            },
            # Test Execution Management
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
                "name": "create_test_execution",
                "description": "Record test execution result",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "case_name": {"type": "STRING"},
                        "status": {"type": "STRING", "description": "Estado: 'pass', 'fail', 'blocked'"},
                        "plan_name": {"type": "STRING"},
                        "build_name": {"type": "STRING"},
                        "project_name": {"type": "STRING"},
                        "notes": {"type": "STRING", "description": "Notas sobre la ejecución (opcional)"}
                    },
                    "required": ["case_name", "status", "plan_name", "build_name", "project_name"]
                }
            },
            # Requirement Management
            {
                "name": "list_requirements",
                "description": "Get all requirements for a project",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "project_name": {"type": "STRING"}
                    },
                    "required": ["project_name"]
                }
            },
            {
                "name": "get_requirement",
                "description": "Get detailed information about a specific requirement",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "req_doc_id": {"type": "STRING"},
                        "project_name": {"type": "STRING"}
                    },
                    "required": ["req_doc_id", "project_name"]
                }
            },
            # Search
            {
                "name": "search_tests",
                "description": "Search for test cases or projects by keywords",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "keywords": {
                            "type": "ARRAY",
                            "items": {"type": "STRING"},
                            "description": "Lista de palabras clave para buscar"
                        }
                    },
                    "required": ["keywords"]
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
        # Recargar configuración para detectar cambios en .env sin reiniciar
        load_dotenv(override=True)

        # Usar configuración de variables de entorno
        testlink_url = os.getenv("TESTLINK_URL")
        api_key = os.getenv("TESTLINK_API_KEY")
        
        #if not api_key:
        
        # Conectar a TestLink
        connected = await mcp_client.connect(testlink_url, api_key)
        if not connected:
            logger.error(f"Fallo al conectar con TestLink en {testlink_url}")
            raise HTTPException(status_code=500, detail=f"No se pudo conectar a TestLink en {testlink_url}")
        
        # Procesar prompt
        result = await mcp_client.process_prompt(request.prompt)
        
        return {
            "success": result.get("success", False),
            "message": result.get("message", ""),
            "action_taken": result.get("action"),
            "data": result.get("data")
        }
    except Exception as e:
        logger.error(f"Error crítico en endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.get("/testlink/health")
async def health_check():
    """Verificar estado del servicio"""
    return {"status": "healthy", "service": "TestLink MCP API"}

@app.get("/testlink/actions")
async def available_actions():
    """Listar capacidades del Agente"""
    return {
        "agent_type": "Strand Agent (RAG + Tools)",
        "capabilities": [
            "Gestión inteligente de proyectos y casos de prueba",
            "Búsqueda semántica y por palabras clave",
            "Creación de elementos con inferencia de contexto",
            "Asistencia en lenguaje natural"
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "testlink_api:app",
        host=os.getenv("API_HOST", "0.0.0.0"), 
        port=int(os.getenv("API_PORT", 8012)),
        log_level=os.getenv("LOG_LEVEL", "info"),
        reload=False  # Deshabilitar reload en producción
    )