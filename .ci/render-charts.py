#!/usr/bin/env python3
"""Render every chart in a repo, every way the repo says it runs, for the gate.

Usage:
    render-charts.py [--helm helm] [--out .rendered] [repo-root]

Why this exists: the App Invariants workflow used to render charts with a shell
loop that skipped anything under */charts/*. Most of our repos keep their
charts in charts/, so for most of the fleet the gate never rendered a single
chart. It read values.yaml comments and reported green. It also only ever
rendered bare defaults, so an HA mode or any other shipped example was never
looked at.

What it does:

  * Finds every Chart.yaml in the repo, at any depth. Helm's own vendored
    subcharts (a charts/ dir sitting next to a Chart.yaml) are someone
    else's and are skipped, same as the old loop skipped them. Everything
    the old loop rendered still renders, archived charts included.
  * Renders each chart with its defaults.
  * Renders each chart again with every values file the repo already ships
    for it: <chart>/examples/*.yaml, <chart>/ci/*values*.yaml, and the repo's
    root examples/*.yaml and ci/*values*.yaml. Root files in a repo with more
    than one chart must name their chart in a helm command in the file, the
    way flux-helm-charts already does ("helm install x charts/weld -f ...").
    Raw manifests, compose files, and YAML lists in examples/ are not values
    files and are listed as skipped, not guessed at.
  * Stamps each render with what it is, so the checker can tell a store
    chart's default render from everything else:
        # app-invariants: rendered chart=<path> values=<defaults|file> store=<yes|no>
    A store chart is one with catalog.cattle.io/display-name in Chart.yaml,
    which is the store's own title key.
  * Carries values.yaml privileged waivers into the render. A comment in
    values.yaml is gone the moment helm runs, so a chart that was correctly
    waived would fail its own render. The renderer flips each waived key to
    false, renders again, and every privileged: true that disappears was
    controlled by that key. It gets the waiver written right above it in the
    render. A privileged: true that does NOT disappear (a hardcoded sidecar)
    gets nothing, and fails like it should.

Failure policy, because a render that silently did not happen is the bug this
replaces: every render must succeed. The one exception is a render the chart
refuses ON PURPOSE with its own fail or required ("must set either
provisioner.enabled=true ...", influxdb's "deploymentMode=ha renders NO
workload"). A refusal installs nothing, so there is nothing in it to check,
and it is printed every run. But a chart has to render at least one way, or
the gate is checking nothing and calling it green. A template crash, broken
YAML, or a values file helm cannot parse is a mode the repo ships that cannot
install, and it fails the gate.

Exit 0 = rendered, 1 = a render failed or a values file is unmappable,
2 = misuse.
"""
import argparse
import difflib
import importlib.util
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RELEASE = "ci"
ARCHIVE_DIRS = ("archive", "_archive")
DELIBERATE_RE = re.compile(r"^Error: execution error at \(", re.M)


def _load_checker():
    """The waiver syntax lives in the checker. Reading it from there means the
    two can never disagree about what a waiver looks like."""
    # No __pycache__ next to the vendored copy; it ends up in commits.
    sys.dont_write_bytecode = True
    path = os.path.join(HERE, "check-app-invariants.py")
    spec = importlib.util.spec_from_file_location("app_invariants", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CHECKER = _load_checker()


def rel(root, p):
    r = os.path.relpath(p, root).replace("\\", "/")
    return r


def find_charts(root):
    charts, skipped = [], []
    for dp, dn, fn in os.walk(root):
        dn[:] = sorted(d for d in dn if d not in (".git", "node_modules", ".rendered"))
        if "Chart.yaml" not in fn:
            continue
        parent = os.path.dirname(dp)
        if (os.path.basename(parent) == "charts"
                and os.path.isfile(os.path.join(os.path.dirname(parent), "Chart.yaml"))):
            continue  # helm's vendored dependency dir, not ours
        # Archived charts get rendered too. The shell loop this replaces
        # rendered micro-vm-pod/_archive, and dropping a render the gate
        # already did is the gate checking less. They are named, not hidden.
        if any(p in ARCHIVE_DIRS for p in rel(root, dp).split("/")):
            skipped.append(dp)
        charts.append(dp)
    return sorted(charts), skipped


def top_keys(text):
    return [m.group(1).strip("\"'") for m in
            re.finditer(r"^([A-Za-z0-9_\"'.-]+)\s*:", text, re.M)]


def values_kind(path):
    """None if this is a values file, else why it is not one."""
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError as e:
        return "unreadable (%s)" % e
    body = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not body:
        return "empty"
    if body[0].lstrip().startswith(("- ", "[")) and _indent0(body[0]):
        return "a YAML list"
    docs = [d for d in re.split(r"^---[ \t]*$", text, flags=re.M)
            if any(l.strip() and not l.lstrip().startswith("#") for l in d.splitlines())]
    if len(docs) > 1:
        return "multi-document"
    keys = top_keys(text)
    if "apiVersion" in keys or "kind" in keys:
        return "a Kubernetes manifest"
    if "services" in keys:
        return "a compose file"
    if not keys:
        return "no top-level keys"
    return None


def _indent0(line):
    return not line[:1].isspace()


def discover_values(root, charts):
    """{chart: [values files]}, skipped [(file, why)], errors [str]."""
    mapping = {c: [] for c in charts}
    skipped, errors = [], []

    def candidates(base):
        out = []
        ex = os.path.join(base, "examples")
        if os.path.isdir(ex):
            out += [os.path.join(ex, f) for f in sorted(os.listdir(ex))
                    if f.endswith((".yaml", ".yml"))]
        ci = os.path.join(base, "ci")
        if os.path.isdir(ci):
            out += [os.path.join(ci, f) for f in sorted(os.listdir(ci))
                    if f.endswith((".yaml", ".yml")) and "values" in f]
        return out

    for c in charts:
        for f in candidates(c):
            why = values_kind(f)
            if why:
                skipped.append((f, why))
            else:
                mapping[c].append(f)

    # A chart that IS the repo root already took the root examples/ and ci/.
    root_c = os.path.abspath(root)
    chart_is_root = any(os.path.abspath(c) == root_c for c in charts)
    for f in [] if chart_is_root else candidates(root):
        why = values_kind(f)
        if why:
            skipped.append((f, why))
            continue
        if len(charts) == 1:
            mapping[charts[0]].append(f)
            continue
        text = open(f, encoding="utf-8", errors="replace").read()

        def named(lines):
            hits = set()
            for c in charts:
                r = re.escape(rel(root, c))
                if any(re.search(r"(^|[\s/=])(\./)?%s/?(\s|$)" % r, l) for l in lines):
                    hits.add(c)
            return hits

        helm_lines = [l for l in text.splitlines()
                      if re.search(r"\bhelm\s+(install|upgrade|template)\b", l)]
        hits = named(helm_lines) or named(text.splitlines())
        if len(hits) == 1:
            mapping[hits.pop()].append(f)
        else:
            errors.append(
                "%s: cannot tell which chart this values file is for (%s). Name "
                "it in the file, e.g. `# helm template x <chart dir> -f %s`."
                % (rel(root, f), "matches " + ", ".join(sorted(rel(root, h) for h in hits))
                   if hits else "names none", rel(root, f)))
    return mapping, skipped, errors


def is_store_chart(chart):
    text = open(os.path.join(chart, "Chart.yaml"), encoding="utf-8", errors="replace").read()
    return bool(re.search(r"^\s+[\"']?catalog\.cattle\.io/display-name[\"']?\s*:", text, re.M))


def visibility(chart):
    """The chart's embernet.ai/visibility annotation. "infra" is how a chart
    tells the dashboard it is Super-only and not a user install (store.go
    reads the same annotation), so an infra chart may choose not to register
    a pod as an app at all. embernet-exec-proxy is the case: it serves pod
    shells for a site and is never itself a tile."""
    text = open(os.path.join(chart, "Chart.yaml"), encoding="utf-8", errors="replace").read()
    m = re.search(r"^\s+[\"']?embernet\.ai/visibility[\"']?\s*:\s*[\"']?([A-Za-z-]+)", text, re.M)
    return m.group(1).lower() if m else "user"


def key_path(lines, idx):
    """The dotted values path of lines[idx], by indentation. Only plain nested
    maps; a key under a list returns None and is left alone rather than
    guessed, because --set on a list index replaces the whole list."""
    path = [re.match(r"^\s*([A-Za-z0-9_.-]+)\s*:", lines[idx]).group(1)]
    ind = CHECKER._indent(lines[idx])
    for j in range(idx - 1, -1, -1):
        l = lines[j]
        if CHECKER._transparent(l):
            continue
        li = CHECKER._indent(l)
        if li < ind:
            if l.lstrip().startswith("- "):
                return None
            m = re.match(r"^\s*([A-Za-z0-9_-]+)\s*:\s*(#.*)?$", l)
            if not m:
                return None
            path.insert(0, m.group(1))
            ind = li
            if ind == 0:
                break
    if ind != 0:
        return None
    return ".".join(path)


def waived_keys(values_path):
    """[(dotted key, 'file:line', reason)] for each written privileged waiver."""
    if not values_path or not os.path.isfile(values_path):
        return []
    lines = open(values_path, encoding="utf-8", errors="replace").read().splitlines()
    out = []
    for i, l in enumerate(lines):
        if not re.match(r"^\s*privileged:\s*true\b", l):
            continue
        window = lines[max(0, i - 6):i + 1]
        wm = None
        for w in window:
            wm = CHECKER.WAIVER_RE.search(w) or wm
        if not wm:
            continue
        reason_line = next(w for w in reversed(window) if CHECKER.WAIVER_RE.search(w))
        # WAIVER_RE ends on the first character of the reason.
        reason = reason_line[CHECKER.WAIVER_RE.search(reason_line).end() - 1:].strip()
        kp = key_path(lines, i)
        if kp:
            out.append((kp, "%s:%d" % (values_path, i + 1), reason))
    return out


def helm(helm_bin, chart, values=None, sets=()):
    cmd = [helm_bin, "template", RELEASE, chart]
    if values:
        cmd += ["-f", values]
    for s in sets:
        cmd += ["--set", s]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout, p.stderr.strip()


def _docs(text):
    return re.split(r"^---[ \t]*$", text, flags=re.M)


def _doc_id(doc):
    k = re.search(r"^kind:\s*(\S+)", doc, re.M)
    n = re.search(r"^metadata:\s*\n(?:[ \t].*\n)*?[ \t]+name:\s*(\S+)", doc, re.M)
    s = re.search(r"^# Source:\s*(\S+)", doc, re.M)
    return (k.group(1) if k else None, n.group(1) if n else None, s.group(1) if s else None)


def carry_waivers(root, helm_bin, chart, values, normal, waivers):
    """Write each values waiver above the rendered privileged lines it controls.
    Returns (new text, [(key, where, n lines carried)])."""
    if not waivers or "privileged: true" not in normal:
        return normal, []
    docs = _docs(normal)
    notes = {}  # (doc index, line index) -> comment
    report = []
    for key, where, reason in waivers:
        code, flipped, err = helm(helm_bin, chart, values, ["%s=false" % key])
        if code:
            report.append((key, where, "could not re-render with %s=false: %s" % (key, err)))
            continue
        fdocs = {}
        for d in _docs(flipped):
            fdocs.setdefault(_doc_id(d), d)
        n = 0
        for di, d in enumerate(docs):
            if not re.search(r"^\s*privileged:\s*true\b", d, re.M):
                continue
            fd = fdocs.get(_doc_id(d), "")
            a, b = d.split("\n"), fd.split("\n")
            sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
            for tag, i1, i2, _, _ in sm.get_opcodes():
                if tag not in ("replace", "delete"):
                    continue
                for li in range(i1, i2):
                    if re.match(r"^\s*privileged:\s*true\b", a[li]):
                        ind = a[li][:len(a[li]) - len(a[li].lstrip())]
                        notes[(di, li)] = "%s# app-invariants: allow-privileged: carried from %s: %s" % (
                            ind, rel(root, where.rsplit(":", 1)[0]) + ":" + where.rsplit(":", 1)[1], reason)
                        n += 1
        report.append((key, where, "%d rendered line(s)" % n))
    if not notes:
        return normal, report
    out = []
    for di, d in enumerate(docs):
        a = d.split("\n")
        for li in sorted((k[1] for k in notes if k[0] == di), reverse=True):
            a.insert(li, notes[(di, li)])
        out.append("\n".join(a))
    return "---".join(out), report


def slug(s):
    s = os.path.basename(s.strip("./")) or "root"
    s = re.sub(r"\.ya?ml$", "", s)
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--out", default=".rendered")
    ap.add_argument("--helm", default=os.environ.get("HELM", "helm"))
    args = ap.parse_args(argv[1:])
    root = args.root
    if not os.path.isdir(root):
        print("render-charts: no such directory: %s" % root, file=sys.stderr)
        return 2
    out_dir = args.out if os.path.isabs(args.out) else os.path.join(root, args.out)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

    charts, archived = find_charts(root)
    for a in archived:
        print("archived, rendered anyway: %s" % rel(root, a))
    if not charts:
        print("render-charts: no charts in this repo, nothing to render")
        return 0

    mapping, skipped, errors = discover_values(root, charts)
    for f, why in skipped:
        print("not a values file, skipped: %s (%s)" % (rel(root, f), why))

    failures = list(errors)
    rendered = 0
    for c in charts:
        rc = rel(root, c) or "."
        # An archived chart keeps its display-name but the store does not list
        # it, so the store rules would be judging a chart nobody installs. Every
        # other rule still runs on it. The checker already treats archive/ as
        # retired (scan_files prunes it).
        archived_chart = c in archived
        store = "yes" if is_store_chart(c) and not archived_chart else "no"
        base_waivers = waived_keys(os.path.join(c, "values.yaml"))
        runs = [(None, "defaults")] + [(v, rel(root, v)) for v in mapping[c]]
        ok = 0
        refused = []
        for vf, label in runs:
            code, text, err = helm(args.helm, c, vf)
            # The baseline is what gets installed when nobody picks a mode:
            # the defaults. A chart that refuses bare defaults has no such
            # render, so its ci/ values files stand in. chart-testing installs
            # a chart once per ci/*-values.yaml for the same reason
            # (helm/chart-testing doc/ct_install.md). examples/ stay what they
            # are, a mode somebody chose.
            baseline = vf is None or (
                any(l == "defaults" for l, _ in refused)
                and "/ci/" in "/" + label.replace("\\", "/"))
            if code:
                # helm writes "execution error at (...)" for the chart's own
                # fail and required, and nothing else: a nil pointer or broken
                # YAML reads "template: ..." or "YAML parse error". A refusal
                # installs nothing, so there is nothing to check in it.
                # Anything else is a mode the repo ships that cannot install.
                if DELIBERATE_RE.search(err):
                    refused.append((label, err))
                else:
                    failures.append("%s with %s did not render: %s" % (rc, label, err))
                continue
            waivers = base_waivers + (waived_keys(vf) if vf else [])
            text, carried = carry_waivers(root, args.helm, c, vf, text, waivers)
            # Short names on purpose: the full path lives in the header, and a
            # long one blows past MAX_PATH on a Windows checkout.
            stem = slug(rc) + ("" if vf is None else "--" + slug(label))
            name, n = stem + ".yaml", 2
            while os.path.exists(os.path.join(out_dir, name)):
                name, n = "%s-%d.yaml" % (stem, n), n + 1
            with open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="\n") as fh:
                fh.write("# app-invariants: rendered chart=%s values=%s store=%s baseline=%s visibility=%s\n"
                         % (rc, label, store, "yes" if baseline else "no", visibility(c)))
                fh.write(text)
            docs = len(re.findall(r"^kind:", text, re.M))
            print("rendered %s [%s] store=%s -> %s (%d objects)" % (rc, label, store, name, docs))
            for key, where, what in carried:
                print("    waiver %s (%s): %s" % (key, rel(root, where.rsplit(":", 1)[0]) + ":" + where.rsplit(":", 1)[1], what))
            rendered += 1
            ok += 1
        for label, err in refused:
            print("refused on purpose: %s with %s: %s" % (rc, label, err.splitlines()[0]))
        if refused and not ok:
            # Every way the repo ships this chart refuses, so the gate would be
            # checking nothing and calling it green. Give it a values file under
            # ci/ that renders the way it really installs.
            failures.append("%s refused every render (%s), so nothing of it was "
                            "checked. Add a ci/*values*.yaml that renders it."
                            % (rc, ", ".join(l for l, _ in refused)))

    if failures:
        print("\nrender-charts: %d problem(s). A chart the gate cannot render is a "
              "chart the gate is not checking:" % len(failures), file=sys.stderr)
        for f in failures:
            print("  " + f, file=sys.stderr)
        return 1
    print("render-charts: %d render(s) from %d chart(s) in %s" % (rendered, len(charts), rel(root, out_dir)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
