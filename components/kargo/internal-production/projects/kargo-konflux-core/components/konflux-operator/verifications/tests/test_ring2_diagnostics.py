"""Run with PROMTOOL=/path/to/promtool python3 -B -m unittest discover -s <this directory>."""
import itertools
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml

COMPONENT = Path(__file__).resolve().parents[2]
PRODUCTION = next(p for p in COMPONENT.parents if p.name == 'internal-production')
TEMPLATE = COMPONENT / 'verifications/kanary-ring-2-diagnostics.yaml'


class Ring2Diagnostics(unittest.TestCase):
    def setUp(self):
        self.template = yaml.safe_load(TEMPLATE.read_text())
        self.stage = yaml.safe_load((COMPONENT / 'stages/ring-2-stage.yaml').read_text())
        self.shared = yaml.safe_load(
            (PRODUCTION / 'shared/verifications/kanary-production.yaml').read_text())
        self.args = {a['name']: a.get('value') for a in self.shared['spec']['args']}
        self.args.update({a['name']: a.get('value') for a in self.template['spec']['args']})
        self.args.update({a['name']: a.get('value')
                          for a in self.stage['spec']['verification']['args']})

    def test_one_run_preserves_gate_and_covers_each_pair(self):
        refs = self.stage['spec']['verification']['analysisTemplates']
        self.assertEqual([r['name'] for r in refs],
                         ['kanary-production', 'kanary-operator-ring-2-diagnostics'])
        metrics = self.template['spec']['metrics']
        pairs = set(itertools.product(self.args['clusters'].split('|'),
                                      self.args['types'].split('|')))
        self.assertEqual(len(pairs), 10)
        actual = set()
        names = set()
        for metric in metrics:
            query = metric['provider']['prometheus']['query']
            cluster = re.search(r'tested_cluster="([^"]+)"', query).group(1)
            kind = re.search(r'type="([^"]+)"', query).group(1)
            actual.add((cluster, kind))
            self.assertNotIn(metric['name'], names)
            names.add(metric['name'])
            self.assertIn(cluster, metric['name'])
            self.assertIn(kind.removeprefix('container-'), metric['name'])
            self.assertTrue(any(re.fullmatch(d['metricName'], metric['name'])
                                for d in self.template['spec']['dryRun']))
            for key in ['initialDelay', 'interval', 'count', 'failureLimit']:
                self.assertEqual(metric[key], self.shared['spec']['metrics'][0][key])
        self.assertEqual(actual, pairs)
        self.assertEqual(len(metrics), len(pairs))
        gate = self.shared['spec']['metrics'][0]
        self.assertFalse(any(re.fullmatch(d['metricName'], gate['name'])
                             for d in self.template['spec']['dryRun']))
        self.assertEqual(self.args['failure-limit'], '7')
        self.assertEqual(self.args['check-count'], '36')
        # Kargo requires every referenced template to declare the Stage arguments;
        # shared defaults must also agree when flattening multiple templates.
        declared = {a['name']: a for a in self.template['spec']['args']}
        for arg in self.shared['spec']['args']:
            self.assertEqual(declared[arg['name']], arg)
        self.assertLessEqual(set(a['name'] for a in self.stage['spec']['verification']['args']),
                             set(declared))

    def test_promql_healthy_failed_missing_and_stale(self):
        promtool = os.environ.get('PROMTOOL') or shutil.which('promtool')
        self.assertIsNotNone(promtool, 'Set PROMTOOL to run the real PromQL fixture tests')
        tests = []
        for metric in self.template['spec']['metrics']:
            query = metric['provider']['prometheus']['query']
            query = re.sub(r'{{args\.([^}]+)}}', lambda m: str(self.args[m[1]]), query)
            cluster = re.search(r'tested_cluster="([^"]+)"', query).group(1)
            kind = re.search(r'type="([^"]+)"', query).group(1)
            labels = f'namespace="konflux-otel",tested_cluster="{cluster}",type="{kind}"'
            def series(name, value, selected=labels):
                return {'series': name + '{' + selected + '}', 'values': str(value) + 'x120'}
            cases = [
                ('healthy', [series('kanary_up', 1), series('kanary_last_push_timestamp', 7200)], [1]),
                ('failed', [series('kanary_up', 0), series('kanary_last_push_timestamp', 7200)], [0]),
                ('missing', [], []),
                ('missing-timestamp', [series('kanary_up', 1)], []),
                ('stale', [series('kanary_up', 1), series('kanary_last_push_timestamp', 3599)], []),
                ('freshness-boundary', [series('kanary_up', 1), series('kanary_last_push_timestamp', 3600)], [1]),
                ('wrong-cluster', [series('kanary_up', 1), series('kanary_last_push_timestamp', 7200,
                    labels.replace(cluster, 'different-cluster'))], []),
                ('wrong-type', [series('kanary_up', 1), series('kanary_last_push_timestamp', 7200,
                    labels.replace(kind, 'different-type'))], []),
                ('stale-series', [{'series': 'kanary_up{' + labels + '}', 'values': '1 stale _x119'},
                                  series('kanary_last_push_timestamp', 7200)], []),
            ]
            for name, inputs, expected in cases:
                tests.append({'name': metric['name'] + '-' + name, 'interval': '1m',
                              'input_series': inputs, 'promql_expr_test': [
                                  {'expr': query, 'eval_time': '2h',
                                   'exp_samples': [{'labels': '{}', 'value': v} for v in expected]}]})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'queries.test.yaml'
            path.write_text(yaml.safe_dump({'evaluation_interval': '1m', 'tests': tests}))
            result = subprocess.run([promtool, 'test', 'rules', str(path)], text=True,
                                    capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(f'Validated {len(tests)} real PromQL fixture cases')


if __name__ == '__main__':
    unittest.main()
