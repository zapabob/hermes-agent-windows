"""Exact parameter selection and identical process fixtures through the canonical runner."""
import ast
import hashlib
import json
import os
from pathlib import Path
import runpy

from verification_v2 import main as prepare, replace_once
from prepare_identity_fixtures import main as prepare_fixtures


def main():
    prepare()
    prepare_fixtures()
    path = Path('.n53-verification/verify.py')
    source = path.read_text(encoding='utf-8')
    before = "    command = [str(BASH), 'scripts/run_tests.sh', target, '-q', f'--junitxml=n53-evidence/{label}.xml']"
    after = '''    file_target, separator, selector = target.partition("::")
    selection = []
    if separator:
        name, bracket, parameter = selector.partition("[")
        if not name.replace("_", "").isalnum():
            raise RuntimeError("Unsupported mutation selector")
        expression = name
        if bracket:
            parameter = parameter.removesuffix("]")
            if not parameter.replace("_", "").isalnum():
                raise RuntimeError("Unsupported mutation parameter")
            expression += " and " + parameter
        selection = ["-k", expression]
    command = [str(BASH), 'scripts/run_tests.sh', file_target, '-q', f'--junitxml=n53-evidence/{label}.xml', *selection]'''
    source = replace_once(source, before, after)
    ast.parse(source)
    path.write_bytes(source.encode('utf-8'))
    os.environ['HERMES_TEST_FILE_RETRIES'] = '0'
    runpy.run_path(str(path), run_name='__main__')
    # These exact bytes, rather than the verification branch's unpatched tree,
    # are the only four files allowed into the production candidate commit.
    allowed = [
        'hermes_cli/update_cmd_windows.py',
        'tests/hermes_cli/test_windows_update_pause_transaction.py',
        'tests/hermes_cli/test_update_concurrent_quarantine.py',
        'tests/hermes_cli/test_windows_gateway_cold_start_desktop_lifecycle.py',
    ]
    receipt = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in allowed}
    Path('n53-evidence/publish-files.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
