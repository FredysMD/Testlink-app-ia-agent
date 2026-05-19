"""
TestLinkHelper — acceso y navegación de la API de TestLink.
"""
import logging
from typing import Dict, List, Optional

import testlink

logger = logging.getLogger("testlink-mcp.helper")


class TestLinkHelper:
    """Encapsula acceso a la API de TestLink con helpers reutilizables."""

    def __init__(self, client: testlink.TestlinkAPIClient):
        self.client = client

    def get_projects(self) -> List[Dict]:
        return self.client.getProjects() or []

    def get_project_id(self, name: str) -> Optional[str]:
        if not name:
            return None
        for p in self.get_projects():
            if p["name"].lower() == name.lower():
                return p["id"]
        return None

    def get_plan_id(self, plan_name: str, project_id: str) -> Optional[str]:
        try:
            for p in (self.client.getProjectTestPlans(project_id) or []):
                if p["name"].lower() == plan_name.lower():
                    return p["id"]
        except testlink.testlinkerrors.TLResponseError as e:
            logger.warning("Error obteniendo planes del proyecto %s: %s", project_id, e)
        return None

    def get_top_suites(self, project_id: str) -> List[Dict]:
        try:
            return self.client.getFirstLevelTestSuitesForTestProject(project_id) or []
        except testlink.testlinkerrors.TLResponseError as e:
            logger.warning("Error obteniendo suites del proyecto %s: %s", project_id, e)
            return []

    def find_suite_recursive(self, suite_name: str, suites: List[Dict]) -> Optional[str]:
        """Busca una suite por nombre de forma recursiva en el árbol."""
        for s in suites:
            if s["name"].lower() == suite_name.lower():
                return s["id"]
            try:
                children = self.client.getTestSuitesForTestSuite(s["id"])
                if isinstance(children, list) and children:
                    found = self.find_suite_recursive(suite_name, children)
                    if found:
                        return found
            except testlink.testlinkerrors.TLResponseError as e:
                logger.debug("Sin sub-suites en '%s': %s", s.get("name"), e)
        return None

    def get_cases_for_suite(self, suite_id: str) -> List[Dict]:
        """Normaliza la respuesta de getTestCasesForTestSuite (dict o list)."""
        raw = self.client.getTestCasesForTestSuite(suite_id, True, "full")
        if isinstance(raw, dict):
            return list(raw.values())
        return raw or []
