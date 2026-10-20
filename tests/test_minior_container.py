"""Prevent passing Node integration tests while omitting runtime files in Docker."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MiniorContainerTests(unittest.TestCase):
    def test_runtime_node_dependencies_are_copied(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        entry = (ROOT / "pvpoke_node_matrix.js").read_text(encoding="utf-8")
        local_dependencies = re.findall(r'require\(["\'](\./[^"\']+)["\']\)', entry)
        self.assertIn("./pvpoke_minior_strategy.js", local_dependencies)
        for dependency in local_dependencies:
            name = dependency.removeprefix("./")
            with self.subTest(name=name):
                self.assertTrue((ROOT / name).is_file())
                self.assertIn(f"COPY {name} /app/{name}", dockerfile)
        self.assertIn('RUN node -e "const s=require(\'./pvpoke_minior_strategy.js\')', dockerfile)


if __name__ == "__main__":
    unittest.main()
