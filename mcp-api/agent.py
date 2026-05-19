"""
TestLinkAgent — gestiona la conexión a TestLink y el loop del agente Gemini.
"""
import json
import logging
from typing import Any, Dict, Optional

import testlink

from config import (
    GEMINI_MODEL,
    GOOGLE_API_KEY,
    MAX_TOOL_ITERATIONS,
    SYSTEM_PROMPT,
    TESTLINK_API_KEY,
    TESTLINK_URL,
    TOOLS,
)
from helpers import TestLinkHelper
from tools import TestLinkTools

try:
    import google.generativeai as genai
    from google.ai.generativelanguage_v1beta.types import content as genai_content
except ImportError:
    genai = None
    genai_content = None

logger = logging.getLogger("testlink-mcp.agent")


class TestLinkAgent:
    """Gestiona conexión a TestLink y el loop del agente Gemini."""

    def __init__(self):
        self._tl_client: Optional[testlink.TestlinkAPIClient] = None
        self._connected_url: Optional[str] = None
        self._connected_key: Optional[str] = None
        self._gemini_model = None

        if genai and GOOGLE_API_KEY:
            genai.configure(api_key=GOOGLE_API_KEY)
            self._gemini_model = genai.GenerativeModel(
                GEMINI_MODEL, system_instruction=SYSTEM_PROMPT
            )
            logger.info("Modelo Gemini inicializado: %s", GEMINI_MODEL)

    def connect(self, url: str = TESTLINK_URL, api_key: str = TESTLINK_API_KEY) -> bool:
        """Conecta a TestLink reutilizando la conexión si los parámetros no cambiaron."""
        if self._tl_client and self._connected_url == url and self._connected_key == api_key:
            return True
        try:
            logger.info("Conectando a TestLink: %s", url)
            client = testlink.TestlinkAPIClient(url, api_key)
            client.about()
            self._tl_client = client
            self._connected_url = url
            self._connected_key = api_key
            logger.info("Conexión exitosa a TestLink")
            return True
        except testlink.testlinkerrors.TLResponseError as e:
            logger.error("Error de autenticación TestLink: %s", e)
        except Exception as e:
            logger.error("Error de conexión inesperado: %s", e, exc_info=True)
        self._tl_client = None
        return False

    def _build_rag_context(self, prompt: str) -> Dict:
        """Recupera metadatos de TestLink relevantes al prompt para contexto RAG."""
        helper = TestLinkHelper(self._tl_client)
        context: Dict = {"projects": []}
        try:
            for p in helper.get_projects():
                info: Dict = {"id": p["id"], "name": p["name"], "prefix": p["prefix"]}
                if p["name"].lower() in prompt.lower():
                    try:
                        plans = self._tl_client.getProjectTestPlans(p["id"]) or []
                        info["plans"] = [{"id": pl["id"], "name": pl["name"]} for pl in plans]
                    except testlink.testlinkerrors.TLResponseError as e:
                        logger.debug("Sin planes para '%s': %s", p["name"], e)
                    try:
                        info["suites"] = [
                            {"id": s["id"], "name": s["name"]}
                            for s in helper.get_top_suites(p["id"])
                        ]
                    except testlink.testlinkerrors.TLResponseError as e:
                        logger.debug("Sin suites para '%s': %s", p["name"], e)
                context["projects"].append(info)
        except testlink.testlinkerrors.TLResponseError as e:
            logger.warning("Error RAG al obtener proyectos: %s", e)
        return context

    @staticmethod
    def _build_summary(tool_results: list, data: list) -> str:
        """Construye un resumen limpio basado en los tool calls ejecutados."""
        if not tool_results:
            return "No se ejecutaron acciones."
        if not data:
            last_name, last_result = tool_results[-1]
            return last_result.get("message", "Operación completada sin resultados.")

        tool_labels = {
            "search_tests": "casos de prueba encontrados",
            "list_test_cases_in_suite": "casos de prueba en la suite",
            "list_projects": "proyectos encontrados",
            "list_test_suites": "suites encontradas",
            "list_test_plans": "planes de prueba encontrados",
            "list_builds": "builds encontrados",
            "list_requirements": "requisitos encontrados",
        }
        last_name, _ = tool_results[-1]
        label = tool_labels.get(last_name, "resultados encontrados")
        return f"Se encontraron {len(data)} {label}."

    async def process_prompt(self, prompt: str) -> Dict[str, Any]:
        """Procesa un prompt en lenguaje natural usando el agente Gemini con tool calling."""
        if not self._gemini_model:
            return {
                "success": False,
                "message": "Modo Agente no disponible. Configura GOOGLE_API_KEY.",
            }

        tools_instance = TestLinkTools(TestLinkHelper(self._tl_client))
        context = self._build_rag_context(prompt)
        initial_message = f"CONTEXTO TESTLINK:\n{json.dumps(context, indent=2)}\n\nUSER: {prompt}"

        try:
            chat = self._gemini_model.start_chat(enable_automatic_function_calling=False)
            response = await chat.send_message_async(
                initial_message,
                tools=TOOLS,
                tool_config={"function_calling_config": {"mode": "AUTO"}},
            )

            tool_results: list = []
            for _ in range(MAX_TOOL_ITERATIONS):
                part = response.parts[0]
                if not part.function_call:
                    break

                fc = part.function_call
                logger.info("Tool call: %s args=%s", fc.name, dict(fc.args))
                tool_result = tools_instance.dispatch(fc.name, dict(fc.args))
                tool_results.append((fc.name, tool_result))

                fn_response = genai_content.FunctionResponse(
                    name=fc.name,
                    response={"result": json.dumps(tool_result, ensure_ascii=False)},
                )
                response = await chat.send_message_async(
                    [genai_content.Part(function_response=fn_response)],
                    tools=TOOLS,
                    tool_config={"function_calling_config": {"mode": "NONE"}},
                )

            all_data = [
                item
                for _, r in tool_results if r.get("data")
                for item in (r["data"] if isinstance(r["data"], list) else [r["data"]])
            ]

            return {
                "success": True,
                "message": self._build_summary(tool_results, all_data),
                "data": all_data if all_data else None,
                "count": len(all_data) if all_data else None,
            }

        except Exception as e:
            logger.error("Error del Agente: %s", e, exc_info=True)
            return {"success": False, "message": f"Error del Agente: {str(e)}"}
