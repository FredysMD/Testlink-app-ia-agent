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
        """Procesa el prompt y determina qué acción tomar en TestLink"""
        prompt_lower = prompt.lower()
        
        # Búsqueda inteligente (debe ir primero)
        if any(word in prompt_lower for word in ["qué", "cuáles", "buscar", "encontrar", "pruebas", "casos", "what", "which", "search", "find", "hay", "existe", "existen"]):
            return await self._search_tests_from_prompt(prompt)
        elif "crear proyecto" in prompt_lower or "create project" in prompt_lower:
            return await self._create_project_from_prompt(prompt)
        elif "listar proyectos" in prompt_lower or "list projects" in prompt_lower:
            return await self._list_projects()
        elif "crear caso" in prompt_lower or "create test case" in prompt_lower:
            return await self._create_test_case_from_prompt(prompt)
        elif "listar casos" in prompt_lower or "list test cases" in prompt_lower:
            return await self._list_test_cases_from_prompt(prompt)
        elif "actualizar caso" in prompt_lower or "update test case" in prompt_lower:
            return await self._update_test_case_from_prompt(prompt)
        elif "eliminar caso" in prompt_lower or "delete test case" in prompt_lower:
            return await self._delete_test_case_from_prompt(prompt)
        elif "crear suite" in prompt_lower or "create test suite" in prompt_lower:
            return await self._create_test_suite_from_prompt(prompt)
        elif "eliminar proyecto" in prompt_lower or "delete project" in prompt_lower:
            return await self._delete_project_from_prompt(prompt)
        else:
            return {
                "action": "unknown",
                "message": "No se pudo determinar la acción a realizar",
                "suggestions": [
                    "crear proyecto [nombre]",
                    "listar proyectos", 
                    "crear caso de prueba [nombre]",
                    "listar casos de prueba",
                    "crear suite [nombre]",
                    "eliminar proyecto [nombre]",
                    "actualizar caso [id]",
                    "eliminar caso [id]",
                    "¿Qué pruebas existen sobre [tema]?",
                    "Buscar casos relacionados con [palabra clave]"
                ]
            }
    
    async def _create_project_from_prompt(self, prompt: str) -> Dict[str, Any]:
        # Extraer nombre del proyecto del prompt
        words = prompt.split()
        if "proyecto" in prompt.lower():
            idx = next((i for i, word in enumerate(words) if "proyecto" in word.lower()), -1)
            if idx != -1 and idx + 1 < len(words):
                project_name = " ".join(words[idx + 1:])
                prefix = "".join([w[0].upper() for w in project_name.split()[:3]])
                
                try:
                    result = self.tl_client.createTestProject(project_name, prefix)
                    return {
                        "action": "create_project",
                        "success": True,
                        "data": result,
                        "message": f"Proyecto '{project_name}' creado exitosamente"
                    }
                except Exception as e:
                    return {
                        "action": "create_project",
                        "success": False,
                        "message": f"Error creando proyecto: {str(e)}"
                    }
        
        return {
            "action": "create_project",
            "success": False,
            "message": "No se pudo extraer el nombre del proyecto del prompt"
        }
    
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
    
    async def _create_test_case_from_prompt(self, prompt: str) -> Dict[str, Any]:
        words = prompt.split()
        if "caso" in prompt.lower():
            idx = next((i for i, word in enumerate(words) if "caso" in word.lower()), -1)
            if idx != -1 and idx + 1 < len(words):
                case_name = " ".join(words[idx + 2:])  # Skip "de prueba"
                try:
                    projects = self.tl_client.getProjects()
                    if projects:
                        project_id = projects[0]['id']
                        # Obtener primera suite disponible
                        suites = self.tl_client.getFirstLevelTestSuitesForTestProject(project_id)
                        if suites:
                            suite_id = suites[0]['id']
                            result = self.tl_client.createTestCase(
                                case_name,
                                suite_id,
                                project_id,
                                "admin",
                                f"Caso de prueba: {case_name}"
                            )
                            return {
                                "action": "create_test_case",
                                "success": True,
                                "data": result,
                                "message": f"Caso '{case_name}' creado exitosamente"
                            }
                        else:
                            return {
                                "action": "create_test_case",
                                "success": False,
                                "message": "No hay suites disponibles. Crea una suite primero."
                            }
                    else:
                        return {
                            "action": "create_test_case",
                            "success": False,
                            "message": "No hay proyectos disponibles. Crea un proyecto primero."
                        }
                except Exception as e:
                    return {
                        "action": "create_test_case",
                        "success": False,
                        "message": f"Error creando caso: {str(e)}"
                    }
        return {
            "action": "create_test_case",
            "success": False,
            "message": "No se pudo extraer el nombre del caso del prompt"
        }
    
    async def _list_test_cases_from_prompt(self, prompt: str) -> Dict[str, Any]:
        try:
            projects = self.tl_client.getProjects()
            all_cases = []
            
            for project in projects:
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
    
    async def _create_test_suite_from_prompt(self, prompt: str) -> Dict[str, Any]:
        words = prompt.split()
        if "suite" in prompt.lower():
            idx = next((i for i, word in enumerate(words) if "suite" in word.lower()), -1)
            if idx != -1 and idx + 1 < len(words):
                suite_name = " ".join(words[idx + 1:])
                try:
                    # Necesitas project_id - usar el primer proyecto disponible
                    projects = self.tl_client.getProjects()
                    if projects:
                        project_id = projects[0]['id']
                        result = self.tl_client.createTestSuite(project_id, suite_name, "Suite creada via API")
                        return {
                            "action": "create_test_suite",
                            "success": True,
                            "data": result,
                            "message": f"Suite '{suite_name}' creada exitosamente"
                        }
                    else:
                        return {
                            "action": "create_test_suite",
                            "success": False,
                            "message": "No hay proyectos disponibles para crear la suite"
                        }
                except Exception as e:
                    return {
                        "action": "create_test_suite",
                        "success": False,
                        "message": f"Error creando suite: {str(e)}"
                    }
        return {
            "action": "create_test_suite",
            "success": False,
            "message": "No se pudo extraer el nombre de la suite del prompt"
        }
    
    async def _delete_project_from_prompt(self, prompt: str) -> Dict[str, Any]:
        return {
            "action": "delete_project",
            "success": False,
            "message": "Eliminación de proyectos deshabilitada por seguridad"
        }
    
    async def _search_tests_from_prompt(self, prompt: str) -> Dict[str, Any]:
        """Busca casos de prueba basado en palabras clave del prompt"""
        try:
            # Extraer términos de búsqueda del prompt
            search_terms = self._extract_search_terms(prompt)
            
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
    
    def _extract_search_terms(self, prompt: str) -> List[str]:
        """Extrae términos de búsqueda relevantes del prompt"""
        import re
        
        # Palabras a ignorar
        stop_words = {'qué', 'que', 'cuáles', 'cuales', 'con', 'en', 'de', 'la', 'el', 'los', 'las', 'un', 'una', 'y', 'o', 'pero', 'si', 'no', 'es', 'son', 'están', 'existe', 'existen', 'hay', 'tiene', 'tienen', 'pruebas', 'casos', 'test', 'tests', 'case', 'cases', 'what', 'which', 'are', 'is', 'there', 'with', 'in', 'of', 'the', 'a', 'an', 'and', 'or', 'but', 'if', 'not', 'para', 'del', 'por', 'desde', 'hasta', 'sobre', 'entre', 'durante', 'dentro'}
        
        # Extraer texto entre comillas como término completo
        quoted_terms = re.findall(r'["\u201c\u201d]([^"\u201c\u201d]+)["\u201c\u201d]', prompt)
        
        # Limpiar y dividir el resto del texto
        clean_prompt = re.sub(r'["\u201c\u201d][^"\u201c\u201d]*["\u201c\u201d]', '', prompt)
        words = re.findall(r'\b\w+\b', clean_prompt.lower())
        
        # Filtrar palabras relevantes
        relevant_words = [word for word in words if word not in stop_words and len(word) > 2]
        
        # Combinar términos entre comillas y palabras relevantes
        search_terms = quoted_terms + relevant_words
        
        return list(set(search_terms))  # Eliminar duplicados
    
    async def _update_test_case_from_prompt(self, prompt: str) -> Dict[str, Any]:
        return {
            "action": "update_test_case",
            "success": False,
            "message": "Para actualizar casos, usa la interfaz web de TestLink por seguridad"
        }
    
    async def _delete_test_case_from_prompt(self, prompt: str) -> Dict[str, Any]:
        return {
            "action": "delete_test_case",
            "success": False,
            "message": "Eliminación de casos deshabilitada por seguridad"
        }

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
        
        if not api_key:
            raise HTTPException(status_code=500, detail="API key no configurada en variables de entorno")
        
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
    """Listar acciones disponibles"""
    return {
        "actions": [
            {
                "name": "crear proyecto [nombre]",
                "description": "Crea un nuevo proyecto en TestLink"
            },
            {
                "name": "listar proyectos", 
                "description": "Lista todos los proyectos disponibles"
            },
            {
                "name": "crear caso de prueba [nombre]",
                "description": "Crea un nuevo caso de prueba"
            },
            {
                "name": "listar casos de prueba",
                "description": "Lista casos de prueba de un proyecto"
            },
            {
                "name": "crear suite [nombre]",
                "description": "Crea una nueva suite de pruebas"
            },
            {
                "name": "eliminar proyecto [nombre]",
                "description": "Elimina un proyecto (deshabilitado por seguridad)"
            },
            {
                "name": "¿Qué pruebas existen sobre [tema]?",
                "description": "Busca casos de prueba relacionados con un tema específico"
            },
            {
                "name": "Buscar casos con [palabra clave]",
                "description": "Encuentra casos de prueba que contengan palabras clave"
            },
            {
                "name": "actualizar caso [id]",
                "description": "Actualizar un caso de prueba existente"
            },
            {
                "name": "eliminar caso [id]",
                "description": "Eliminar un caso de prueba (deshabilitado por seguridad)"
            }
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