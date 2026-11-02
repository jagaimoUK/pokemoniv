#!/usr/bin/env python3
"""Read-only Google Cloud Run validation readiness inventory.

No API enablement, billing edits, IAM changes, secret reads, image pushes or deploys.
Only aggregate readiness results are printed; account identities and CLI stderr are hidden.
"""
import argparse
import json
import re
import subprocess
from typing import Callable

PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
RESOURCE_RE = re.compile(r"^[a-z][a-z0-9-]{1,61}[a-z0-9]$")
REGION_RE = re.compile(r"^[a-z]+-[a-z0-9]+[0-9]$")

REQUIRED_APIS = {
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
}


def gcloud(arguments: list[str]) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            ["gcloud", *arguments], capture_output=True, text=True,
            timeout=35, check=False,
        )
        return completed.returncode, completed.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 127, ""


def inspect(project: str, region: str, service: str = "pokemoniv-validation",
            repository: str = "pokemoniv-validation",
            runner: Callable[[list[str]], tuple[int, str]] = gcloud) -> dict:
    if not PROJECT_RE.fullmatch(project):
        raise ValueError("Invalid project ID; use a Google Cloud project ID, not a display name")
    if not REGION_RE.fullmatch(region):
        raise ValueError("Invalid region (example: us-central1)")
    if not RESOURCE_RE.fullmatch(service) or "validation" not in service:
        raise ValueError("Service name must be a validation-only name")
    if not RESOURCE_RE.fullmatch(repository) or "validation" not in repository:
        raise ValueError("Repository name must be a validation-only name")

    def call(*args: str) -> tuple[int, str]:
        return runner(list(args))

    rc, account = call("auth", "list", "--filter=status:ACTIVE",
                       "--format=value(account)")
    auth = rc == 0 and bool(account)
    rc, bill = call("billing", "projects", "describe", project,
                    "--format=value(billingEnabled)")
    billing = "enabled" if rc == 0 and bill.lower() == "true" else (
        "disabled" if rc == 0 and bill.lower() == "false" else "unknown_or_denied"
    )
    rc, apis = call("services", "list", "--enabled", "--project=" + project,
                    "--format=value(config.name)")
    enabled = set(apis.splitlines()) if rc == 0 else set()
    api_status = {api: ("enabled" if api in enabled else
                        "not_enabled" if rc == 0 else "unknown_or_denied")
                  for api in sorted(REQUIRED_APIS)}

    rc, _ = call("artifacts", "repositories", "describe", repository,
                 "--project=" + project, "--location=" + region,
                 "--format=value(name)")
    registry = "found" if rc == 0 else "missing_or_denied"

    service_rc, description = call("run", "services", "describe", service,
                           "--project=" + project, "--region=" + region,
                           "--format=json")
    label = "unknown"
    private = "unknown"
    if service_rc == 0:
        try:
            data = json.loads(description)
            label = data.get("metadata", {}).get("labels", {}).get(
                "pokemoniv_role", "missing"
            )
            rc, policy = call("run", "services", "get-iam-policy", service,
                              "--project=" + project, "--region=" + region,
                              "--format=json")
            if rc == 0:
                members = {member for binding in json.loads(policy).get("bindings", [])
                           for member in binding.get("members", [])}
                private = "no" if ("allUsers" in members or
                                   "allAuthenticatedUsers" in members) else "yes"
        except (ValueError, TypeError, AttributeError):
            label = "invalid"
    return {
        "project": project,
        "region": region,
        "account_authenticated": auth,
        "billing_state": billing,
        "required_apis": api_status,
        "validation_registry": registry,
        "validation_service": "found" if service_rc == 0 and label != "unknown" else
                              "missing_or_denied",
        "validation_label": label,
        "service_private_iam": private,
        "budget_and_cloud_run_spend_cap": "not_checked_requires_manual_review",
        "validation_secret_and_service_accounts": "not_checked_requires_manual_review",
        "actions_performed": "READ_ONLY",
        "ready_for_review": auth and billing == "enabled" and
            all(v == "enabled" for v in api_status.values()) and
            registry == "found" and label == "validation" and private == "yes",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--service", default="pokemoniv-validation")
    parser.add_argument("--repository", default="pokemoniv-validation")
    args = parser.parse_args()
    try:
        report = inspect(args.project, args.region, args.service, args.repository)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ready_for_review"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
