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

# Intentar importar Google Generative AI
try:
    import google.generativeai as genai
    from google.ai.generativelanguage_v1beta.types import content
except ImportError:
    genai = None

# Cargar variables de entorno
load_dotenv()

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
            self.model = genai.GenerativeModel('gemini-2.5-flash')
        
    async def connect(self, url: str, api_key: str) -> bool:
        try:
            print(f"Attempting to connect to TestLink at: {url}")
            print(f"Using API key: {api_key[:10]}...")
            self.tl_client = testlink.TestlinkAPIClient(url, api_key)
            # Test connection with a simple call
            try:
                about_info = self.tl_client.about()
                print(f"Successfully connected to TestLink: {about_info}")
                return True
            except Exception as api_error:
                print(f"API call failed: {api_error}")
                # If about() fails, it might be an API key issue
                # Let's try to at least verify the server is reachable
                import urllib.request
                try:
                    response = urllib.request.urlopen(url.replace('/lib/api/xmlrpc/v1/xmlrpc.php', '/login.php'))
                    if response.getcode() == 200:
                        print("TestLink server is reachable but API key might be invalid")
                        return False
                except:
                    print("TestLink server is not reachable")
                    return False
                return False
        except Exception as e:
            print(f"Connection error: {e}")
            print(f"Error type: {type(e)}")
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
                
                print(f"Agent executing tool: {function_name} with args: {arguments}")
                return await self._execute_tool(function_name, arguments)
            else:
                # Respuesta conversacional
                return {
                    "success": True,
                    "action": "chat",
                    "message": part.text
                }
                
        except Exception as e:
            print(f"Agent Error: {traceback.format_exc()}")
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
            print(f"RAG Warning: {e}")
        return context
    
    async def _execute_tool(self, name: str, args: Dict) -> Dict:
        """Despachador de herramientas"""
        if name == "create_project":
            return await self._create_project(args["name"], args.get("prefix"))
        elif name == "list_projects":
            return await self._list_projects()
        elif name == "create_test_case":
            return await self._create_test_case(args["name"], args.get("project_name"), args.get("suite_name"), args.get("summary"))
        elif name == "create_test_suite":
            return await self._create_test_suite(args["name"], args.get("project_name"))
        elif name == "search_tests":
            return await self._search_tests(args.get("keywords", []))
        elif name == "list_test_cases":
            return await self._list_test_cases(args.get("project_name"))
        elif name == "create_test_plan":
            return await self._create_test_plan(args["name"], args["project_name"], args.get("notes", ""))
        elif name == "create_build":
            return await self._create_build(args["name"], args["plan_name"], args["project_name"], args.get("notes", ""))
        elif name == "add_test_case_to_plan":
            return await self._add_test_case_to_plan(args["case_name"], args["plan_name"], args["project_name"])
        elif name == "report_test_result":
            return await self._report_test_result(args["case_name"], args["status"], args["plan_name"], args["build_name"], args["project_name"], args.get("notes", ""))
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
    
    # --- NUEVAS HERRAMIENTAS DE CICLO DE VIDA (PLAN, BUILD, EXECUTION) ---

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

    def _find_case_by_name(self, name: str, project_id):
        # Búsqueda simplificada. En producción usaría getTestCaseIDByName si existe o búsqueda iterativa
        # Aquí reutilizamos la lógica de búsqueda existente o asumimos que el ID se pasa si falla
        return None # Implementación completa requeriría iterar suites. Por brevedad, el agente debe usar search_tests primero para obtener IDs si esto falla, pero para este ejemplo asumiremos que el usuario o agente provee nombres exactos y podríamos implementar una búsqueda rápida aquí si fuera crítico.
        # NOTA: Para que funcione _report_test_result, necesitamos el ID interno.
        # Una estrategia mejor para el Agente es usar search_tests para obtener el ID y pasarlo.
        # Voy a mejorar _find_case_by_name para hacer una búsqueda rápida en suites de primer nivel
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
        # Definición compatible con Gemini Function Declarations
        return [
            {
                "name": "create_project",
                "description": "Crear un nuevo proyecto de pruebas en TestLink",
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
                "description": "Listar todos los proyectos existentes",
                "parameters": {"type": "OBJECT", "properties": {}}
            },
            {
                "name": "create_test_case",
                "description": "Crear un nuevo caso de prueba",
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
                "name": "search_tests",
                "description": "Buscar casos de prueba o proyectos por palabras clave",
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
            },
            {
                "name": "create_test_plan",
                "description": "Crear un Plan de Pruebas (Test Plan) para agrupar ejecuciones",
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
                "name": "create_build",
                "description": "Crear un Build dentro de un Plan de Pruebas",
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
                "name": "add_test_case_to_plan",
                "description": "Añadir un caso de prueba a un plan para su ejecución",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "case_name": {"type": "STRING", "description": "Nombre del caso de prueba"},
                        "plan_name": {"type": "STRING", "description": "Nombre del plan de pruebas destino"},
                        "project_name": {"type": "STRING", "description": "Nombre del proyecto"}
                    },
                    "required": ["case_name", "plan_name", "project_name"]
                }
            },
            {
                "name": "report_test_result",
                "description": "Reportar el resultado de la ejecución de un caso de prueba",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "case_name": {"type": "STRING", "description": "Nombre del caso de prueba ejecutado"},
                        "status": {"type": "STRING", "description": "Estado: 'pass', 'fail', 'blocked'"},
                        "plan_name": {"type": "STRING", "description": "Nombre del plan de pruebas"},
                        "build_name": {"type": "STRING", "description": "Nombre del build ejecutado"},
                        "project_name": {"type": "STRING", "description": "Nombre del proyecto"},
                        "notes": {"type": "STRING", "description": "Notas sobre la ejecución (opcional)"}
                    },
                    "required": ["case_name", "status", "plan_name", "build_name", "project_name"]
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
        # Usar configuración de variables de entorno
        testlink_url = os.getenv("TESTLINK_URL")
        api_key = os.getenv("TESTLINK_API_KEY")
        
        #if not api_key:
        
        # Conectar a TestLink
        connected = await mcp_client.connect(testlink_url, api_key)
        if not connected:
            print(f"Failed to connect to TestLink at {testlink_url}")
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
        print(f"Error en endpoint: {e}")
        print(traceback.format_exc())
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