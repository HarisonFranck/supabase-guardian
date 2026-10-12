
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

TIMEOUT = 20
MAX_ATTEMPTS = 2


def check_project(project):
    name = project["name"]
    base_url = project["url"].rstrip("/")
    api_key = project["anon_key"]

    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    result = {
        "project": name,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "database": "ERROR",
        "edge_function": "NOT_CONFIGURED",
        "errors": [],
    }

    for attempt in range(MAX_ATTEMPTS):
        try:
            response = requests.post(
                f"{base_url}/rest/v1/rpc/guardian_ping",
                headers=headers,
                json={},
                timeout=TIMEOUT,
            )

            if response.status_code == 200:
                body = response.json()
                if body.get("ok") is True:
                    result["database"] = "OK"
                    break
                result["errors"].append("Unexpected RPC response")
            else:
                result["errors"].append(
                    f"RPC returned HTTP {response.status_code}"
                )

            # Une erreur d'autorisation ne sera pas résolue par un retry.
            if response.status_code in (401, 403, 404):
                break

        except requests.RequestException as exc:
            result["errors"].append(
                f"RPC network error: {type(exc).__name__}"
            )

        if attempt + 1 < MAX_ATTEMPTS:
            time.sleep(3)

    edge_name = project.get("edge_function", "").strip()

    if edge_name:
        # Autoriser uniquement un nom de fonction simple.
        if "/" in edge_name or ".." in edge_name:
            result["edge_function"] = "ERROR"
            result["errors"].append("Invalid Edge Function name")
        else:
            try:
                response = requests.get(
                    f"{base_url}/functions/v1/{edge_name}",
                    headers=headers,
                    timeout=TIMEOUT,
                )
                if response.status_code == 200:
                    result["edge_function"] = "OK"
                else:
                    result["edge_function"] = "ERROR"
                    result["errors"].append(
                        f"Edge Function returned HTTP "
                        f"{response.status_code}"
                    )
            except requests.RequestException as exc:
                result["edge_function"] = "ERROR"
                result["errors"].append(
                    f"Edge Function network error: "
                    f"{type(exc).__name__}"
                )

    return result


def main():
    raw = os.environ.get("SUPABASE_PROJECTS_JSON", "")

    try:
        projects = json.loads(raw)
        if not isinstance(projects, list) or not projects:
            raise ValueError("Project list must not be empty")

        for project in projects:
            if not isinstance(project, dict):
                raise ValueError("Each project must be an object")

            if not all(
                project.get(key)
                for key in ("name", "url", "anon_key")
            ):
                raise ValueError(
                    "Each project requires name, url and anon_key"
                )

            if not project["url"].startswith("https://"):
                raise ValueError("Project URLs must use HTTPS")

    except (ValueError, json.JSONDecodeError) as exc:
        print(f"Configuration error: {exc}")
        return 2

    results = [check_project(project) for project in projects]

    for result in results:
        print(json.dumps(result, ensure_ascii=False))

    failures = [
        item for item in results
        if item["database"] != "OK"
        or item["edge_function"] == "ERROR"
    ]

    if failures:
        print(
            f"FAILED: {len(failures)} of {len(results)} "
            "project checks failed."
        )
        return 1

    print(f"SUCCESS: all {len(results)} projects passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
