"""
TestLinkTools — implementación de cada herramienta del agente.
"""
import logging
from typing import Any, Dict, List, Optional

import testlink

from helpers import TestLinkHelper

logger = logging.getLogger("testlink-mcp.tools")


class TestLinkTools:
    """Implementa cada herramienta del agente y expone un despachador único."""

    def __init__(self, helper: TestLinkHelper):
        self.h = helper

    # --- Respuestas estándar ---

    def _ok(self, data: Any, count: bool = True) -> Dict:
        result: Dict = {"success": True, "data": data}
        if count and isinstance(data, list):
            result["count"] = len(data)
        return result

    def _err(self, msg: str) -> Dict:
        return {"success": False, "message": msg}

    # --- Herramientas ---

    def list_projects(self) -> Dict:
        projects = self.h.get_projects()
        for p in projects:
            if isinstance(p, dict):
                p.pop("api_key", None)
        return self._ok(projects)

    def read_test_case(self, test_case_external_id: str) -> Dict:
        result = self.h.client.getTestCase(testcaseexternalid=test_case_external_id)
        if not result:
            return self._err("Caso no encontrado")
        return self._ok(result, count=False)

    def get_test_case_details(self, test_case_external_id: str) -> Dict:
        result = self.h.client.getTestCase(testcaseexternalid=test_case_external_id)
        if not result:
            return self._err("Caso no encontrado")
        tc = result[0] if isinstance(result, list) else result
        return self._ok({
            "external_id": tc.get("full_tc_external_id", test_case_external_id),
            "name": tc.get("name"),
            "summary": tc.get("summary", ""),
            "preconditions": tc.get("preconditions", ""),
            "steps": tc.get("steps", []),
            "author": tc.get("author_login", "Desconocido"),
            "creation_ts": tc.get("creation_ts", ""),
        }, count=False)

    def list_test_suites(self, project_name: str) -> Dict:
        project_id = self.h.get_project_id(project_name)
        if not project_id:
            return self._err("Proyecto no encontrado")
        return self._ok(self.h.get_top_suites(project_id))

    def list_test_plans(self, project_name: str) -> Dict:
        project_id = self.h.get_project_id(project_name)
        if not project_id:
            return self._err("Proyecto no encontrado")
        plans = self.h.client.getProjectTestPlans(project_id) or []
        return self._ok(plans)

    def list_builds(self, plan_name: str, project_name: str) -> Dict:
        project_id = self.h.get_project_id(project_name)
        plan_id = self.h.get_plan_id(plan_name, project_id) if project_id else None
        if not plan_id:
            return self._err("Plan no encontrado")
        builds = self.h.client.getBuildsForTestPlan(plan_id) or []
        return self._ok(builds)

    def read_test_execution(self, test_case_external_id: str, plan_name: str, project_name: str) -> Dict:
        project_id = self.h.get_project_id(project_name)
        plan_id = self.h.get_plan_id(plan_name, project_id) if project_id else None
        if not plan_id:
            return self._err("Plan no encontrado")
        result = self.h.client.getLastExecutionResult(plan_id, testcaseexternalid=test_case_external_id)
        return self._ok(result, count=False)

    def list_test_cases_in_suite(self, suite_name: str, project_name: str) -> Dict:
        project_id = self.h.get_project_id(project_name)
        if not project_id:
            return self._err("Proyecto no encontrado")
        suite_id = self.h.find_suite_recursive(suite_name, self.h.get_top_suites(project_id))
        if not suite_id:
            return self._err(f"Suite '{suite_name}' no encontrada")
        cases = [
            {
                "external_id": c.get("full_tc_external_id", c.get("id")),
                "name": c.get("name"),
                "author": c.get("author_login", "Desconocido"),
                "summary": (c.get("summary") or "")[:200],
            }
            for c in self.h.get_cases_for_suite(suite_id)
            if isinstance(c, dict)
        ]
        return self._ok(cases)

    def list_requirements(self, project_name: str) -> Dict:
        project_id = self.h.get_project_id(project_name)
        if not project_id:
            return self._err("Proyecto no encontrado")
        specs = self.h.client.getRequirementSpecifications(project_id) or []
        all_reqs: List[Dict] = []
        for spec in specs:
            reqs = self.h.client.getRequirementsForRequirementSpecification(spec["id"], project_id)
            if reqs:
                all_reqs.extend(reqs)
        return self._ok(all_reqs)

    def search_tests(self, keyword: str, project_name: Optional[str] = None) -> Dict:
        projects = self.h.get_projects()
        if project_name:
            projects = [p for p in projects if p["name"].lower() == project_name.lower()]
            if not projects:
                return self._err("Proyecto no encontrado")

        kw = keyword.lower()
        matches: List[Dict] = []
        for project in projects:
            for suite in self.h.get_top_suites(project["id"]):
                try:
                    for case in self.h.get_cases_for_suite(suite["id"]):
                        text = f"{case.get('name','')} {case.get('summary','')} {case.get('steps','')}".lower()
                        if kw in text:
                            matches.append({
                                "external_id": case.get("full_tc_external_id", case.get("id")),
                                "name": case.get("name"),
                                "project": project["name"],
                                "suite": suite["name"],
                            })
                except testlink.testlinkerrors.TLResponseError as e:
                    logger.warning("Error en suite '%s': %s", suite.get("name"), e)
        return self._ok(matches)

    # --- Despachador ---

    def dispatch(self, name: str, args: Dict) -> Dict:
        handlers = {
            "list_projects":            lambda: self.list_projects(),
            "read_test_case":           lambda: self.read_test_case(args.get("test_case_external_id")),
            "get_test_case_details":    lambda: self.get_test_case_details(args.get("test_case_external_id")),
            "list_test_suites":         lambda: self.list_test_suites(args.get("project_name")),
            "list_test_plans":          lambda: self.list_test_plans(args.get("project_name")),
            "list_builds":              lambda: self.list_builds(args.get("plan_name"), args.get("project_name")),
            "read_test_execution":      lambda: self.read_test_execution(
                args.get("test_case_external_id"), args.get("plan_name"), args.get("project_name")
            ),
            "list_test_cases_in_suite": lambda: self.list_test_cases_in_suite(
                args.get("suite_name"), args.get("project_name")
            ),
            "list_requirements":        lambda: self.list_requirements(args.get("project_name")),
            "search_tests":             lambda: self.search_tests(args.get("keyword"), args.get("project_name")),
        }
        handler = handlers.get(name)
        if not handler:
            return {"success": False, "message": f"Herramienta desconocida: {name}"}
        return handler()
