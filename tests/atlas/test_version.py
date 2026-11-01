"""Release identity must agree across installed metadata and runtime."""
import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).parents[2]


class VersionTests(unittest.TestCase):
    def test_release_version_matches_runtime_changelog_and_container(self):
        config = (ROOT / 'ftst_atlas/config.yaml').read_text()
        version = re.search(r'^version: "([^\"]+)"$', config, re.M).group(1)
        tree = ast.parse((ROOT / 'ftst_atlas/app.py').read_text())
        runtime = next(ast.literal_eval(node.value) for node in tree.body
                       if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == 'VERSION' for target in node.targets))
        self.assertEqual(runtime, version)
        self.assertTrue((ROOT / 'ftst_atlas/CHANGELOG.md').read_text().startswith('## ' + version + '\n'))
        workflow = (ROOT / '.github/workflows/tests.yml').read_text()
        self.assertIn('BUILD_VERSION=' + version + ' --build-arg BUILD_ARCH=amd64 -t ftst-atlas:test', workflow)
