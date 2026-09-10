"""Source-authored expectations; see fixture REVIEW.md for semantic rationale."""
import json
from pathlib import Path
import pytest
from feynmap import FeynMapEngine, evaluate_graph

ROOT = Path(__file__).parent / 'fixtures' / 'adversarial'


@pytest.mark.parametrize('case', ['python_scope', 'javascript_scope', 'http_methods'])
def test_source_authored_relationships(case):
    root = ROOT / case
    graph = FeynMapEngine().analyze(str(root))
    report = evaluate_graph(graph, json.loads((root / 'annotations.json').read_text()))
    assert report['status'] == 'pass', report['relationships']


def test_python_runtime_witness():
    import subprocess
    import sys
    script = '''
import sys
import consumer
from pkg.impl import helper
seen = []
def trace(frame, event, arg):
    if event == 'call' and frame.f_code is helper.__code__:
        seen.append('package')
sys.setprofile(trace)
assert consumer.actual() == 'package'
assert len(seen) == 1
assert consumer.parameter(lambda: 'parameter') == 'parameter'
assert consumer.local() == 'local'
assert len(seen) == 1
sys.setprofile(None)
'''
    subprocess.run([sys.executable, '-c', script], cwd=str(ROOT / 'python_scope'), check=True,
                   capture_output=True, text=True, timeout=10)


def test_javascript_runtime_witness():
    import shutil
    import subprocess
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is required only for runtime witness validation')
    script = r'''
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const calls = [];
const scope = vm.createContext({});
vm.runInContext(fs.readFileSync('javascript_scope/app.js', 'utf8'), scope);
scope.helper = () => { calls.push('global'); return 'global'; };
assert.equal(scope.actual(), 'global');
assert.equal(calls.length, 1);
assert.equal(scope.member({helper: () => 'object'}), 'object');
assert.equal(scope.commentOnly(), 0);
assert.equal(scope.stringOnly(), 'helper()');
assert.equal(scope.outer(), 0);
assert.equal(calls.length, 1);
const requests = [];
const http = vm.createContext({fetch: (url, options = {}) => requests.push([url, options.method || 'GET'])});
vm.runInContext(fs.readFileSync('http_methods/client.js', 'utf8'), http);
http.readItems(); http.writeItems();
assert.deepEqual(requests, [['/items', 'GET'], ['/items', 'POST']]);
'''
    subprocess.run([node, '-e', script], cwd=str(ROOT), check=True,
                   capture_output=True, text=True, timeout=10)


def test_mask_preserves_positions_and_balances_calls():
    from feynmap.adapters.javascript_lexical import code_mask, call_end
    text = 'fetch("(x)", {method: "POST" /* ) */}); // fake()\nnext()'
    masked = code_mask(text)
    assert len(masked) == len(text)
    assert masked.count('\n') == text.count('\n')
    assert 'fake' not in masked
    assert call_end(masked, masked.index('(')) == text.index(');')
    assert call_end('fetch(', 5) == -1
