import json
import sys
from pathlib import Path


def parse_env_file(env_path: str):
    settings = []

    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            # skip comments / blanks
            if not line or line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, value = line.split("=", 1)

            key = key.strip()

            # remove quotes if present
            value = value.strip().strip('"').strip("'")

            settings.append({
                "name": key,
                "value": value,
                "slotSetting": False
            })

    return settings


def main():
    env_file = sys.argv[1] if len(sys.argv) > 1 else ".env"
    output_file = "appsettings.json"

    settings = parse_env_file(env_file)

    # Add Azure flags automatically (optional but handy)
    settings.extend([
        {
            "name": "SCM_DO_BUILD_DURING_DEPLOYMENT",
            "value": "true",
            "slotSetting": False
        },
        {
            "name": "WEBSITE_RUN_FROM_PACKAGE",
            "value": "0",
            "slotSetting": False
        }
    ])

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)

    print(f"✅ Created {output_file} with {len(settings)} settings")


if __name__ == "__main__":
    main()
