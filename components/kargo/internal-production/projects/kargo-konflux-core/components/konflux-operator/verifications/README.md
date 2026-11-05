# Operator Ring 2 cluster diagnostics

Only `ring-2-konflux-operator` references this template. Kargo combines it with
`kanary-production` into **one AnalysisRun** containing eleven metrics:

- The existing `kanary-up` aggregate promotion gate.
- Ten `kanary-up-<cluster>-<type>` diagnostic metrics: single-arch and multi-arch
  checks for kflux-fedora-01, kflux-ocp-p01, kflux-osp-p01, kflux-prd-rh03,
  and stone-prod-p01.

The diagnostic names match `spec.dryRun`; the aggregate name does not. Failed or
errored diagnostic metrics therefore do not decide whether the run succeeds.
The original aggregate query and its failure allowance remain unchanged, so
failures distributed across clusters cannot gain a separate promotion allowance
per cluster. Other components and operator rings are unchanged.

## Interpreting a measurement

Each query selects one exact cluster/type pair and requires a corresponding
`kanary_last_push_timestamp` no older than 3,600 seconds:

- `[1]`: a fresh `kanary_up=1` signal.
- `[0]`: a fresh `kanary_up=0` signal; the diagnostic measurement fails.
- `[]`: the signal or timestamp is missing/stale; the diagnostic measurement fails.
- Provider/query errors remain visible as diagnostic errors.

A missing type cannot be hidden by another healthy type. Freshness joins include
both `tested_cluster` and `type`. The one-hour threshold is an initial diagnostic
setting, allowing two configured 30-minute test-start intervals; production test
completion/ingestion latency has not been observed. Adjust the template's
`max-signal-age-seconds` default after inspecting real results. Do not add this
argument to the Stage unless every referenced template also declares it.

`kanary_up=1` is not a complete proof of test success: the current Kanary producer
also emits it for unknown outcomes alongside `kanary_error=1`. These diagnostics
measure the existing up signal with freshness, not processing-error reasons.
Investigate `kanary_error` and its `reason`/`phase` labels separately. An empty
error result alone does not prove success, and the dashboard's two-minute error
filter is not suitable as a new gate sampled only every 40 minutes.

The Stage still supplies the 40-minute initial delay, 40-minute interval,
36 measurements and seven-failure allowance. Diagnostic metrics use the same
settings and retain up to 36 measurements each. A metric/run can terminate early
according to Argo Rollouts limits; retention is not a promise of 36 samples.
Metric names and exact selectors are explicit. If the Stage's clusters or types
change, update this template too; the tests detect an inconsistent inventory.

## Local validation

Prerequisites: Python 3 with PyYAML, `kustomize`, and Prometheus `promtool`.
From the repository root:

```sh
PROMTOOL=/path/to/promtool python3 -B -m unittest discover \
  -s components/kargo/internal-production/projects/kargo-konflux-core/components/konflux-operator/verifications/tests
kustomize build components/kargo/internal-production/projects/kargo-konflux-core/
```

The tests check exact cluster/type coverage, argument compatibility, diagnostic
selection without disabling the aggregate gate, and matching timing settings.
They execute the actual template queries using `promtool test rules` with
healthy, failing, missing, stale, freshness-boundary, and mismatched-label series.
No production credentials are required. Live RHOBS behavior and the Kargo UI
remain unverified until this is reconciled and an operator promotion runs.

Kargo's composition and argument contracts are documented at
<https://docs.kargo.io/user-guide/how-to-guides/verification>.
