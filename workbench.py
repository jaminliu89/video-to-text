"""DRE Media Studio: default product UI, legacy preview at /legacy.

Shared inference engines and existing MCP/API remain in the same process.
"""
from v2t import studio_api  # register browser routes, upload and editing API
from v2t.workbench_ui import run

if __name__ == "__main__":
    run()
