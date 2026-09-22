"""Fail-closed integration into the workflow kernel; host receipts are test doubles."""
from __future__ import annotations

import dataclasses
import importlib
import inspect
import unittest

from test_kernel import Host
from test_security_contract import route_config


class RouteAdmissionTests(unittest.TestCase):
    def setUp(self):
        try:
            self.k = importlib.import_module("downstream.implementation_router.kernel")
            self.r = importlib.import_module("downstream.implementation_router.routes")
            self.s = importlib.import_module("downstream.implementation_router.security")
        except ModuleNotFoundError:
            self.fail("ImplementationRouter contract is not implemented on this base")
        self.binding = self.k.RunBinding("secure-run", "secure-workspace")
        self.routes = self.r.RoutingTable.from_config(route_config())
        self.host = Host(self.k)
        self.receipt = self.s.CredentialFreeAdmission("secure-run", "secure-workspace", self.routes.fingerprint())
        self.host.admit = lambda binding, routes: self.receipt

    def run_router(self):
        self.assertIn("routing", inspect.signature(self.k.ImplementationRouter).parameters)
        return self.k.ImplementationRouter(routing=self.routes).run(
            task="Implement", binding=self.binding, required_checks=("unit",), host=self.host)

    def test_default_is_disabled_without_any_model_call(self):
        result = self.k.ImplementationRouter().run(
            task="Implement", binding=self.binding, required_checks=("unit",), host=self.host)
        self.assertEqual(result.state, "BLOCKED")
        self.assertEqual(result.reason, "routing_disabled")
        self.assertEqual(self.host.calls, [])

    def test_configured_stage_routes_reach_trusted_host_not_handoff(self):
        result = self.run_router()
        self.assertEqual(result.state, "SUCCEEDED")
        for request in self.host.calls:
            self.assertEqual(request.route, self.routes.for_role(request.role))
            self.assertNotIn(request.route.model, request.handoff_json)
            self.assertNotIn("api_key", request.handoff_json)

    def test_unavailable_credential_boundary_stops_before_inference(self):
        self.host.admit = lambda binding, routes: None
        result = self.run_router()
        self.assertEqual(result.reason, "credential_boundary_unavailable")
        self.assertEqual(self.host.calls, [])
        self.assertEqual(self.host.verifications, [])

    def test_cross_run_or_dictionary_security_receipts_are_rejected(self):
        for value in (True, dataclasses.asdict(self.receipt), dataclasses.replace(self.receipt, run_id="wrong")):
            with self.subTest(value=type(value)):
                self.host.admit = lambda binding, routes: value
                result = self.run_router()
                self.assertEqual(result.state, "BLOCKED")
                self.assertEqual(self.host.calls, [])

    def test_revoked_admission_prevents_next_stage(self):
        calls = []
        def admit(binding, routes):
            calls.append(True)
            return self.receipt if not self.host.calls else None
        self.host.admit = admit
        result = self.run_router()
        self.assertEqual(result.state, "BLOCKED")
        self.assertEqual([r.role for r in self.host.calls], ["planner"])

    def test_revoked_admission_prevents_verification(self):
        self.host.admit = lambda binding, routes: self.receipt if len(self.host.calls) < 2 else None
        result = self.run_router()
        self.assertEqual(result.state, "BLOCKED")
        self.assertEqual(self.host.verifications, [])

    def test_boundary_error_does_not_echo_secrets(self):
        def broken(binding, routes):
            raise RuntimeError("synthetic-key-in-provider-error")
        self.host.admit = broken
        result = self.run_router()
        self.assertEqual(result.reason, "credential_boundary_unavailable")
        self.assertNotIn("synthetic-key", str(result))
        self.assertEqual(self.host.calls, [])
