#!/usr/bin/env python3
# app-invariants: fixtures
#
# ^ Required. The throwaway charts below are privileged and carry a
# NetworkPolicy on purpose; they are the assertions.
"""Regression suite for render-charts.py. It needs helm on PATH (or $HELM).

The renderer is half the gate now. If it quietly renders nothing, the checker
scans nothing and says green, which is exactly what the old shell loop did to
every repo that keeps its charts in charts/. So it gets the same treatment the
checker gets: throwaway repos, and a case for each thing it must do.

Usage:
    python3 test-render-charts.py [-v]
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RENDERER = os.environ.get("RENDER_CHARTS", os.path.join(HERE, "render-charts.py"))
CHECKER = os.path.join(HERE, "check-app-invariants.py")
VERBOSE = "-v" in sys.argv[1:]

STORE_CHART = """apiVersion: v2
name: app
version: 0.1.0
annotations:
  catalog.cattle.io/display-name: "App"
"""

PLAIN_CHART = """apiVersion: v2
name: %s
version: 0.1.0
"""

# A store app: pod and Service labeled, main container privileged from values
# and waived there, plus a sidecar that is privileged no matter what.
DEPLOY = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}
spec:
  template:
    metadata:
      labels:
        embernet.ai/store-app: "true"
        embernet.ai/app-name: app
        embernet.ai/gui-type: web
        embernet.ai/gui-port: "8080"
    spec:
      containers:
        - name: main
          securityContext:
            privileged: {{ .Values.securityContext.privileged }}
{{- if .Values.sidecar }}
        - name: sidecar
          securityContext:
            privileged: {{ "true" }}
{{- end }}
"""
# ^ Spelled as a template so the RAW template scan does not see it; only the
# render does. That is the case the renderer has to get right: a privileged
# line no values key controls.

SERVICE = """apiVersion: v1
kind: Service
metadata:
  name: {{ .Release.Name }}
  labels:
    embernet.ai/store-app: "true"
    embernet.ai/app-name: app
    embernet.ai/gui-type: web
    embernet.ai/gui-port: "8080"
"""

WAIVED_VALUES = """sidecar: false
securityContext:
  # app-invariants: allow-privileged: Patrick's call, PLC runtime needs host devices
  privileged: true
"""


def write(root, files):
    for p, content in files.items():
        full = os.path.join(root, p)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)


def run(cmd, cwd):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def render(root):
    return run([sys.executable, RENDERER, "--out", ".rendered", "."], root)


def check(root, *paths):
    return run([sys.executable, CHECKER] + list(paths), root)


def rendered(root):
    d = os.path.join(root, ".rendered")
    out = {}
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        out[f] = open(os.path.join(d, f), encoding="utf-8").read()
    return out


def app_chart(prefix="charts/app", values=WAIVED_VALUES):
    return {
        prefix + "/Chart.yaml": STORE_CHART,
        prefix + "/values.yaml": values,
        prefix + "/templates/deploy.yaml": DEPLOY,
        prefix + "/templates/svc.yaml": SERVICE,
    }


def case_charts_dir_is_rendered(root):
    """The bug this whole file exists for: charts/ used to be skipped."""
    write(root, app_chart())
    code, out = render(root)
    r = rendered(root)
    assert code == 0, out
    assert "app.yaml" in r, "charts/app was not rendered: %s" % out
    assert "values=defaults store=yes" in r["app.yaml"].splitlines()[0], r["app.yaml"][:200]
    assert "visibility=user" in r["app.yaml"].splitlines()[0], r["app.yaml"][:200]
    # A chart that says embernet.ai/visibility: infra gets it in the header.
    write(root, {"charts/app/Chart.yaml": STORE_CHART + "  embernet.ai/visibility: infra\n"})
    render(root)
    assert "visibility=infra" in rendered(root)["app.yaml"].splitlines()[0], rendered(root)["app.yaml"][:200]


def case_vendored_subchart_skipped_archive_still_rendered(root):
    """The old loop skipped vendored subcharts and rendered _archive. Same now."""
    files = app_chart()
    files["charts/app/charts/dep/Chart.yaml"] = PLAIN_CHART % "dep"
    files["_archive/Chart.yaml"] = PLAIN_CHART % "old"
    write(root, files)
    code, out = render(root)
    assert code == 0, out
    assert sorted(rendered(root)) == ["_archive.yaml", "app.yaml"], sorted(rendered(root))
    assert "archived, rendered anyway: _archive" in out, out
    # The store does not list an archived chart, so the store rules skip it.
    files = {"_archive/Chart.yaml": STORE_CHART}
    write(root, files)
    render(root)
    assert "store=no" in rendered(root)["_archive.yaml"].splitlines()[0]


def case_waiver_carried_only_to_the_line_it_controls(root):
    files = app_chart(values=WAIVED_VALUES.replace("sidecar: false", "sidecar: true"))
    write(root, files)
    code, out = render(root)
    assert code == 0, out
    text = rendered(root)["app.yaml"]
    lines = text.splitlines()
    priv = [i for i, l in enumerate(lines) if l.strip() == "privileged: true"]
    assert len(priv) == 2, text
    assert "carried from charts/app/values.yaml:4" in lines[priv[0] - 1], lines[priv[0] - 1]
    assert "allow-privileged" not in lines[priv[1] - 1], lines[priv[1] - 1]
    # And the checker agrees: the waived one counts, the hardcoded sidecar fails.
    code, out = check(root, ".rendered")
    assert code == 1 and out.count("privileged-no-caps") == 1, out
    assert "1 privileged waiver(s) in force" in out, out


def case_waived_chart_passes_clean(root):
    write(root, app_chart())
    render(root)
    code, out = check(root, "charts", ".rendered")
    assert code == 0, out


def case_examples_rendered_and_manifests_skipped(root):
    files = app_chart()
    files["examples/ha.yaml"] = "replicaCount: 3\n"
    files["examples/policy.yaml"] = "apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\n"
    files["charts/app/ci/lint-values.yaml"] = "replicaCount: 2\n"
    write(root, files)
    code, out = render(root)
    assert code == 0, out
    r = rendered(root)
    assert "app--ha.yaml" in r and "values=examples/ha.yaml" in r["app--ha.yaml"], sorted(r)
    assert "app--lint-values.yaml" in r, sorted(r)
    assert "not a values file, skipped: examples/policy.yaml (a Kubernetes manifest)" in out, out


def case_default_networkpolicy_fails_the_gate(root):
    files = app_chart()
    files["charts/app/templates/np.yaml"] = (
        "apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\n"
        "metadata:\n  name: deny\nspec:\n  podSelector: {}\n")
    write(root, files)
    render(root)
    code, out = check(root, ".rendered")
    assert code == 1 and "networkpolicy-default" in out, out


def case_root_examples_map_by_helm_line(root):
    files = app_chart()
    files["charts/other/Chart.yaml"] = PLAIN_CHART % "other"
    files["charts/other/templates/cm.yaml"] = "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: x\n"
    files["examples/app-ha.yaml"] = "# helm install x charts/app -f examples/app-ha.yaml\nreplicaCount: 3\n"
    write(root, files)
    code, out = render(root)
    assert code == 0, out
    assert "app--app-ha.yaml" in rendered(root), sorted(rendered(root))


def case_unmappable_root_example_fails(root):
    files = app_chart()
    files["charts/other/Chart.yaml"] = PLAIN_CHART % "other"
    files["examples/mystery.yaml"] = "replicaCount: 3\n"
    write(root, files)
    code, out = render(root)
    assert code == 1 and "cannot tell which chart" in out, out


def case_deliberate_refusal_needs_another_render(root):
    files = app_chart()
    files["charts/app/templates/guard.yaml"] = (
        "{{- if not .Values.identity }}{{ fail \"must set identity\" }}{{ end }}\n")
    write(root, files)
    code, out = render(root)
    assert code == 1 and "refused every render" in out, out
    write(root, {"ci/app-values.yaml": "identity: stub\n"})
    code, out = render(root)
    assert code == 0, out
    assert "refused on purpose: charts/app with defaults" in out, out
    assert "app--app-values.yaml" in rendered(root), sorted(rendered(root))
    # With no default render, the ci/ render is the baseline, so a
    # NetworkPolicy the chart ships unconditionally is still caught.
    assert "baseline=yes" in rendered(root)["app--app-values.yaml"].splitlines()[0]
    write(root, {"charts/app/templates/np.yaml":
                 "apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: deny\n"})
    render(root)
    code, out = check(root, ".rendered")
    assert code == 1 and "networkpolicy-default" in out, out


def case_broken_values_file_fails(root):
    files = app_chart()
    files["examples/broken.yaml"] = "a:\n  b: 1\n c: 2\n"
    write(root, files)
    code, out = render(root)
    assert code == 1 and "examples/broken.yaml did not render" in out, out


CASES = [v for k, v in sorted(globals().items()) if k.startswith("case_")]


def main():
    code, out = run([os.environ.get("HELM", "helm"), "version", "--short"], HERE)
    if code:
        print("test-render-charts: helm is not available: %s" % out, file=sys.stderr)
        return 2
    failures = 0
    for fn in CASES:
        with tempfile.TemporaryDirectory() as td:
            try:
                fn(td)
                if VERBOSE:
                    print("ok    %s" % fn.__name__)
            except AssertionError as e:
                failures += 1
                print("FAIL  %s\n        %s" % (fn.__name__, str(e)[:1500]))
    if failures:
        print("\n%d/%d renderer case(s) FAILED. Fix the renderer before trusting "
              "any green: a render that did not happen is a chart nobody checked."
              % (failures, len(CASES)))
        return 1
    print("render-charts: %d/%d regression case(s) pass" % (len(CASES), len(CASES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
