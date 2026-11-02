"""Never call Google Cloud during unit tests. All results are synthetic."""
import importlib.util
import pathlib
import unittest

FILE = pathlib.Path(__file__).resolve().parents[1] / "tools" / "cloud_run_validation_preflight.py"
SPEC = importlib.util.spec_from_file_location("cloud_run_validation_preflight", FILE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fake(commands):
    command = tuple(commands)
    if command[:2] == ("auth", "list"):
        return 0, "synthetic@example.invalid"
    if command[:3] == ("billing", "projects", "describe"):
        return 0, "True"
    if command[:2] == ("services", "list"):
        return 0, "\n".join(sorted(MODULE.REQUIRED_APIS))
    if command[:3] == ("artifacts", "repositories", "describe"):
        return 0, "projects/test-project-1/locations/us-central1/repositories/pokemoniv-validation"
    if command[:3] == ("run", "services", "describe"):
        return 0, '{"metadata":{"labels":{"pokemoniv_role":"validation"}}}'
    if command[:3] == ("run", "services", "get-iam-policy"):
        return 0, '{"bindings":[{"role":"roles/run.invoker","members":["user:synthetic@example.invalid"]}]}'
    raise AssertionError("Unexpected or mutating gcloud invocation: " + repr(commands))


class PreflightTest(unittest.TestCase):
    def test_ready_is_read_only(self):
        calls = []
        def runner(arguments):
            calls.append(arguments)
            return fake(arguments)
        result = MODULE.inspect("test-project-1", "us-central1", runner=runner)
        self.assertTrue(result["ready_for_review"])
        self.assertEqual(result["actions_performed"], "READ_ONLY")
        self.assertNotIn("synthetic@", str(result))
        self.assertEqual(len(calls), 6)
        for args in calls:
            self.assertFalse(any(token in args for token in (
                "deploy", "create", "delete", "enable", "update", "push",
                "add-iam-policy-binding", "access"
            )))

    def test_refuse_public_service(self):
        def runner(args):
            if args[:3] == ["run", "services", "get-iam-policy"]:
                return 0, '{"bindings":[{"members":["allUsers"]}]}'
            return fake(args)
        result = MODULE.inspect("test-project-1", "us-central1", runner=runner)
        self.assertFalse(result["ready_for_review"])
        self.assertEqual(result["service_private_iam"], "no")

    def test_refuse_disabled_invoker_iam_check(self):
        def runner(args):
            if args[:3] == ["run", "services", "describe"]:
                return 0, ('{"metadata":{"labels":{"pokemoniv_role":"validation"},'
                           '"annotations":{"run.googleapis.com/invoker-iam-disabled":"true"}}}')
            return fake(args)
        result = MODULE.inspect("test-project-1", "us-central1", runner=runner)
        self.assertFalse(result["ready_for_review"])
        self.assertEqual(result["service_private_iam"], "no")

    def test_refuse_production_resource_names(self):
        with self.assertRaises(ValueError):
            MODULE.inspect("test-project-1", "us-central1", service="pokemoniv")
        with self.assertRaises(ValueError):
            MODULE.inspect("test-project-1", "us-central1", repository="pokemoniv")
        with self.assertRaises(ValueError):
            MODULE.inspect("PROJECT_SECRET", "us-central1")

    def test_unknown_gcloud_permissions_fail_closed(self):
        result = MODULE.inspect(
            "test-project-1", "us-central1", runner=lambda args: (1, ""))
        self.assertFalse(result["ready_for_review"])
        self.assertEqual(result["billing_state"], "unknown_or_denied")
        self.assertNotEqual(result["service_private_iam"], "yes")


if __name__ == "__main__":
    unittest.main()
