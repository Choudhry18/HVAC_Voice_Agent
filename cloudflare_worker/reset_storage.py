import json
import subprocess
import tempfile
from pathlib import Path


worker_directory = Path(__file__).parent
config_path = worker_directory / "wrangler.jsonc"

result = subprocess.run(
    [
        "npx",
        "--yes",
        "wrangler",
        "kv",
        "key",
        "list",
        "--binding",
        "CALLERS",
        "--remote",
        "--prefix",
        "caller:",
        "--config",
        str(config_path),
    ],
    cwd=worker_directory,
    check=True,
    capture_output=True,
    text=True,
)

output = result.stdout
keys = json.loads(output[output.find("[") : output.rfind("]") + 1])
records = [{"key": item["name"], "value": ""} for item in keys]

if not records:
    print("No caller records found.")
    raise SystemExit(0)

confirmation = input(f"Delete {len(records)} caller record(s)? [y/N] ")
if confirmation.lower() != "y":
    print("Reset canceled.")
    raise SystemExit(0)

with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as delete_file:
    json.dump(records, delete_file)
    delete_file.flush()
    subprocess.run(
        [
            "npx",
            "--yes",
            "wrangler",
            "kv",
            "bulk",
            "delete",
            delete_file.name,
            "--binding",
            "CALLERS",
            "--remote",
            "--force",
            "--config",
            str(config_path),
        ],
        cwd=worker_directory,
        check=True,
    )

print(f"Deleted {len(records)} caller record(s).")
