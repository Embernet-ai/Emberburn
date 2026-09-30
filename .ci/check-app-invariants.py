#!/usr/bin/env python3
"""Enforce the app-template invariants against chart templates and manifests.

Every rule here corresponds to an outage, and every one of them is SILENT: the
workload comes up, reports healthy, and moves no traffic. That is precisely why
this runs in CI instead of living in a README — the README already said some of
this and the fleet drifted anyway.

Usage:
    check-app-invariants.py <path> [<path> ...]

Paths may be chart directories, manifest directories, or single files.
Exit 0 = clean, 1 = violations found, 2 = the checker refuses to answer.

Helm templating is handled by ignoring lines that are pure Go-template control
flow and by treating `{{ ... }}` values as unknown rather than as literals: the
goal is to catch hardcoded mistakes, not to render the chart. A value that comes
from `.Values` is the operator's business and is skipped with a note.

Scripts are scanned too (`.py`, `.sh`), because the Ziti services on this estate
are wired by scripts rather than manifests — a YAML-only checker had never once
looked at the two intercept literals it was written to catch.

Two behaviours worth knowing before you trust a green:

  * Exit 2 means UNTRUSTWORTHY, not clean. It fires when any named path matched
    zero files, so a stale argument in a multi-path sweep fails loudly instead
    of quietly reporting success over a tree nobody read.
  * `privileged: true` is waivable IN WRITING and every waiver is counted in the
    output (see WAIVER_RE). Some workloads genuinely need it; an exception that
    stops being visible becomes the new default.

The rules are covered both ways — must-fire and must-not-cry-wolf — by
test-check-app-invariants.py, which lives beside this file and runs in CI. Run
it after any edit here; three of this checker's first four findings across the
fleet were false positives, and a check that cries wolf gets switched off.
"""
import os
import re
import sys

# The router's DNS intercept pool. Anything static in here collides with what
# the tunneler allocates dynamically. Keep in step with
# fluxrouter.DefaultDNSInterceptCIDR and the_reconciler config.flux_intercept_pool.
#
# The `(?!/\d)` tail matters: an address carrying a prefix length is a RANGE
# DECLARATION, not an allocated address. `--dnsSvcIpRange 100.65.0.0/16` IS the
# pool; it is not an intercept inside the pool. Without this, flux-edge-tunnel
# could never document its own CLI argument, and a rule that punishes accurate
# documentation gets the documentation deleted.
#
# Known narrowing, stated rather than hidden: an intercept written as
# `100.65.1.1/32` is now missed. That is a deliberate trade against three false
# positives on the chart most likely to be read.
DNS_POOL_RE = re.compile(r"\b100\.65\.\d{1,3}\.\d{1,3}\b(?!/\d)")

# WireGuard node ranges: a real machine lives at these, and intercepting one
# shadows it on every dialer.
NODE_RANGE_RE = re.compile(r"\b100\.64\.[012]\.\d{1,3}\b(?!/\d)")

TEMPLATED = re.compile(r"\{\{.*?\}\}")

# Extensions worth reading. `.py` and `.sh` are here because the Ziti services
# on this estate are wired by SCRIPTS, not manifests — fragua-edge-01-designer
# and fragua-edge-02-designer carry their intercept literals in
# Fragua-Demo/deploy/flux/wire-fragua-designer-ziti-services.py. A checker that
# reads only YAML has never looked at the two offenders it was written for. The
# line-scan rules below work unchanged on script source; nothing else does.
SCAN_EXTS = (".yaml", ".yml", ".tpl", ".py", ".sh")

# A values file is an INPUT to a chart, not an object spec. Whether the pod ends
# up with the right dnsPolicy is decided by the TEMPLATE, and the good charts
# DERIVE it — node-exporter, alert-manager and postgresql all emit
#
#     {{- if .Values.network.hostNetwork }}
#     hostNetwork: true
#     dnsPolicy: ClusterFirstWithHostNet
#
# and expose no dnsPolicy key at all. That is the STRONGEST form of the
# invariant: an input that cannot be set wrong beats an input plus a guard. So
# "no dnsPolicy key here" does NOT mean "no dnsPolicy on the pod", and the
# ABSENCE rule is undecidable on a values file. Skip rather than guess — the
# same call already made for the RWO/Recreate rule below.
#
# A values file that NAMES a wrong policy is still decidable and still fails.
# That is flux-l2-bridge (dnsPolicy: Default with hostNetwork: true) and it must
# keep failing, so only the absence case is skipped.
VALUES_FILE_RE = re.compile(
    r"(?:^|[\\/])values[^\\/]*\.ya?ml$|(?:^|[\\/])examples[\\/]", re.I)

# An explicit, reasoned waiver for `privileged: true`.
#
# Some workloads genuinely need it and a capability list cannot replace it: the
# flux tunnelers do tproxy, install nft rules, open raw sockets and want their
# own tun device, and CAP_* grants no /dev access. Pretending otherwise would
# mean either a permanently red check or a chart that lies.
#
# So the rule is not switched off — it is waivable, and only in writing. The
# marker must carry a reason after the em-dash, and every waiver is COUNTED in
# the summary, so exceptions stay greppable instead of dissolving into silence.
#
#     securityContext:
#       # app-invariants: allow-privileged — tunneler does tproxy + nft + raw
#       # sockets and creates its own tun device.
#       privileged: true
WAIVER_RE = re.compile(
    r"#\s*app-invariants:\s*allow-privileged\s*[-—:]\s*\S", re.I)

# A file declaring itself as fixture data. Test suites for these very rules must
# contain known-bad addresses on purpose — this checker's own regression suite
# does, and so does the_reconciler/tests/test_intercept_guard.py, which lists
# the designer literals precisely to assert that the guard rejects them. Without
# an opt-out, every such test file is a permanent violation and the only way to
# get a green is to delete the tests.
#
# Deliberately a written marker rather than a path heuristic like "tests/": the
# declaration is visible in the file it applies to, and it is greppable.
FIXTURES_RE = re.compile(r"#\s*app-invariants:\s*fixtures\b", re.I)

# Keys whose VALUES are certificate names, not addressing declarations.
#
# A tls-san list is the set of names a serving cert must cover, and during an
# address migration it legitimately holds BOTH the old and new addresses — that
# is the entire point of it. templates/k3s/k3s-config.server.fragua.yaml lists
# fragua-k3s-api.flux.internal, its current 100.64.65.2, its retired 100.65.1.1
# and two node addresses, so that agents dialing any of them still get valid
# TLS. Reading those as intercepts produced three findings on a file that is
# correct, and the only way to "fix" it would be to break every agent's TLS.
#
# The node-range rule was already hedged behind `"intercept" in text`, but that
# matched the WORD in a prose comment, which is how this fired at all.
SAN_KEYS = {
    "tls-san", "tls-sans", "cert-san", "cert-sans", "certsans",
    "apiservercertsans", "subjectaltnames", "dnsnames", "ipaddresses",
}

KEY_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+):\s*(?:#.*)?$|^\s*([A-Za-z0-9_.-]+):\s+\S")


class Finding:
    def __init__(self, path, line, rule, detail):
        self.path, self.line, self.rule, self.detail = path, line, rule, detail

    def __str__(self):
        loc = "%s:%d" % (self.path, self.line) if self.line else self.path
        return "  [%s] %s\n      %s" % (self.rule, loc, self.detail)


# The same waiver, expressed so it SURVIVES RENDERING.
#
# A comment in values.yaml is gone the moment `helm template` runs, so a chart
# could be correctly waived and still fail when CI scans the rendered manifest
# -- which is exactly what happened to codesys-app the first time this gate
# ran. Worse: nothing scanning a LIVE object could ever see the reason either.
#
# As a pod annotation the reason travels with the workload: into the rendered
# YAML, into the cluster, and into `kubectl get -o yaml` at 2am.
#
#     annotations:
#       app-invariants.embernet.ai/allow-privileged: "needs host device nodes"
WAIVER_ANNOTATION_RE = re.compile(
    "app-invariants[.]embernet[.]ai/allow-privileged:" + r"\s*\S", re.I)


# The header render-charts.py writes on top of every rendered manifest:
#
#     # app-invariants: rendered chart=chart values=defaults store=yes
#
# Some rules are only decidable on a render. A NetworkPolicy is only a crime in
# what gets installed when nobody touched a value, and a missing store label
# only matters on an app the store lists. Neither can be read off one YAML
# document, so the renderer says what the file is and the checker believes it.
# No header, no rule: raw templates and hand-written manifests are judged
# exactly as they always were.
RENDERED_RE = re.compile(r"^#\s*app-invariants:\s*rendered\b(.*)$", re.M)

# The labels the dashboard lists an app by. It selects pods and Services on
# store-app=true and reads the rest off whatever it found.
STORE_APP = "embernet.ai/store-app"
STORE_REQUIRED = ("embernet.ai/app-name", "embernet.ai/gui-type")
GUI_PORT_KEYS = ("embernet.ai/gui-port", "embernet.ai/gui-ports")

# Where each kind keeps the pod metadata the dashboard actually reads. The
# Deployment's OWN labels are not what the dashboard sees; the pod's are.
POD_META_PATH = {
    "Deployment": ("spec", "template", "metadata"),
    "StatefulSet": ("spec", "template", "metadata"),
    "DaemonSet": ("spec", "template", "metadata"),
    "ReplicaSet": ("spec", "template", "metadata"),
    "Job": ("spec", "template", "metadata"),
    "CronJob": ("spec", "jobTemplate", "spec", "template", "metadata"),
    "VirtualMachine": ("spec", "template", "metadata"),
    "Pod": ("metadata",),
}

NETPOL_KIND_RE = re.compile(r"^kind:\s*[\"']?(\w*NetworkPolicy)\b", re.M)
CAPS_NEEDED = ("NET_ADMIN", "NET_RAW", "NET_BIND_SERVICE")


def _indent(line):
    return len(line) - len(line.lstrip(" "))


def _transparent(line):
    """Lines that carry no YAML structure: blanks, comments, and pure Go
    template control flow like `{{- if .Values.x }}`, which sits at column 0 in
    a raw template and would otherwise read as the end of every block."""
    s = line.strip()
    return (not s or s.startswith("#")
            or (s.startswith("{{") and s.endswith("}}")))


def _siblings(lines, idx):
    """(start, end) of the mapping that holds lines[idx]: everything between
    the nearest shallower line above and below. Children of the siblings are
    inside the range too; callers that want only true siblings filter on
    indent themselves.

    This is what "the same securityContext" and "the same pod spec" mean in a
    file that holds more than one of them."""
    ind = _indent(lines[idx])
    start = idx
    for j in range(idx - 1, -1, -1):
        if _transparent(lines[j]):
            continue
        # Shallower means we walked out of the mapping. A list item at our own
        # indent means we walked into the previous item of a list.
        if _indent(lines[j]) < ind or (
                _indent(lines[j]) == ind and lines[j].lstrip().startswith("- ")):
            break
        start = j
    end = idx + 1
    for j in range(idx + 1, len(lines)):
        if _transparent(lines[j]):
            end = j + 1
            continue
        if _indent(lines[j]) < ind:
            break
        # A new list item at our own indent is a new mapping, not a sibling.
        if _indent(lines[j]) == ind and lines[j].lstrip().startswith("- "):
            break
        end = j + 1
    return start, end


def _code(line):
    """A line without its trailing comment, so prose can never satisfy a rule
    that only a real value should."""
    return re.sub(r"(^|\s)#.*$", "", line)


def _parse_scalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v


def _child(lines, start, end, key):
    """Find `key:` as a direct child of the block lines[start:end]. Returns
    (key_line, block_start, block_end) or None. The child indent is whatever
    the first real line in the block uses, which is how YAML defines it."""
    first = next((i for i in range(start, end) if not _transparent(lines[i])), None)
    if first is None:
        return None
    ind = _indent(lines[first])
    pat = re.compile(r"^\s{%d}[\"']?%s[\"']?\s*:(\s|$)" % (ind, re.escape(key)))
    for i in range(first, end):
        if _transparent(lines[i]):
            continue
        if _indent(lines[i]) < ind:
            return None
        if pat.match(lines[i]):
            j = i + 1
            while j < end and (_transparent(lines[j]) or _indent(lines[j]) > ind):
                j += 1
            return i, i + 1, j
    return None


def _mapping(lines, path):
    """The string map at `path` in one YAML document (block or flow style),
    or None when the path is not there. Only as much YAML as helm emits for
    metadata; this is not a parser and does not pretend to be."""
    start, end = 0, len(lines)
    hit = None
    for key in path:
        hit = _child(lines, start, end, key)
        if hit is None:
            return None
        _, start, end = hit
    kl = lines[hit[0]]
    inline = kl.split(":", 1)[1].strip() if ":" in kl else ""
    inline = _code(inline).strip()
    out = {}
    if inline.startswith("{"):
        for m in re.finditer(r"[\"']?([^\"',{}:\s]+)[\"']?\s*:\s*(\"[^\"]*\"|'[^']*'|[^,}]+)", inline):
            out[m.group(1)] = _parse_scalar(m.group(2))
        return out
    first = next((i for i in range(start, end) if not _transparent(lines[i])), None)
    if first is None:
        return out
    ind = _indent(lines[first])
    for i in range(first, end):
        if _transparent(lines[i]) or _indent(lines[i]) != ind:
            continue
        m = re.match(r"^\s*(\"[^\"]+\"|'[^']+'|[^:\s][^:]*?)\s*:\s*(.*)$", _code(lines[i]))
        if m:
            out[_parse_scalar(m.group(1))] = _parse_scalar(m.group(2))
    return out


def _docs(text):
    """(offset, body) for every YAML document in `text`, offsets exact so a
    finding points at the right line even when two documents are identical."""
    out = []
    pos = 0
    for m in re.finditer(r"^---[ \t]*$", text, re.M):
        out.append((pos, text[pos:m.start()]))
        pos = m.end()
    out.append((pos, text[pos:]))
    return out


def _enclosing_doc(text, offset):
    """The YAML document containing `offset`.

    Scoping the annotation waiver per document means one workload's exception
    cannot silence another's in a multi-object rendered manifest.
    """
    bounds = [mm.start() for mm in re.finditer(r'^---[ 	]*$', text, re.M)]
    starts = [0] + [b + 4 for b in bounds]
    ends = bounds + [len(text)]
    for a, b in zip(starts, ends):
        if a <= offset < b:
            return text[a:b]
    return text


def scan_files(root):
    """Yield every file worth checking under `root`.

    The `charts` prune is deliberately NARROW. It exists to skip Helm's vendored
    dependency directory — the `charts/` that sits INSIDE a chart, next to its
    Chart.yaml, holding somebody else's subcharts. Pruning every directory that
    happens to be named `charts` also skipped the top-level `charts/` that most
    of our app repos keep their own charts in, and the effect was a confident,
    permanent green over code nobody had opened. Measured before the fix:

        check-app-invariants.py Codesys-AMD-64-x86-live         -> 0 violations
        check-app-invariants.py .../charts/codesys-pod          -> 1 violation

    The scanned==0 guard in main() did not catch it either, because six
    unrelated docs at the repo root were scanned. That is the same class of bug
    as the guard itself was written to prevent, one level up.
    """
    if os.path.isfile(root):
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        vendored = os.path.isfile(os.path.join(dirpath, "Chart.yaml"))
        dirnames[:] = [
            d for d in dirnames
            if d not in (".git", "node_modules", "archive")
            and not (d == "charts" and vendored)
        ]
        for fn in filenames:
            if fn.endswith(SCAN_EXTS):
                yield os.path.join(dirpath, fn)


def _check_rendered(path, text):
    """Rules that only mean something on a store chart's rendered output.

    Both are Patrick's store contract, and both used to live only in release
    checklists and in whoever happened to remember them. A rule that lives in a
    checklist gets skipped the one time it matters.
    """
    head = "\n".join(text.splitlines()[:5])
    hm = RENDERED_RE.search(head)
    if not hm:
        return []
    attrs = dict(re.findall(r"(\w+)=(\S+)", hm.group(1)))
    out = []

    # --- No NetworkPolicy in any chart's default render ---------------------
    #
    # Every store app has to reach every other store app, over Services and
    # over Flux. HotLoop shipped networkPolicy.enabled: true once, the gateway
    # could only hear 8080 and the historian only the gateway, and every other
    # app on the box went deaf to it. The rule I wrote down after that says NO
    # chart ships one on by default, store or not, so this runs on every
    # chart's default render. Any policy that selects a pod isolates it for
    # its policyTypes (kubernetes.io/docs/concepts/services-networking/
    # network-policies, "The two sorts of pod isolation"), so there is no
    # harmless flavor. A chart can keep a policy template, off by default. An
    # operator who turns it on in their own values made that call.
    #
    # baseline=yes marks the render that stands in for defaults when a chart
    # refuses to render bare (Network-Probe needs an identity first). Without
    # it a chart could dodge this rule just by refusing its defaults.
    if attrs.get("values") == "defaults" or attrs.get("baseline") == "yes":
        for m in NETPOL_KIND_RE.finditer(text):
            out.append(Finding(
                path, text[:m.start()].count("\n") + 1, "networkpolicy-default",
                "%s rendered with DEFAULT values. Defaults are what gets "
                "installed, so this ships a restrictive policy to everyone and "
                "cuts the app off from every other app. Put it behind "
                "networkPolicy.enabled, default false." % m.group(1)))

    if attrs.get("store") != "yes":
        return out

    # --- Store labels on the things the dashboard lists ----------------------
    #
    # The dashboard finds apps by selecting pods and Services on
    # embernet.ai/store-app=true and reads app-name, gui-type and gui-port off
    # whatever it found. A pod without store-app is an app that is running and
    # invisible. A web app without gui-port gets its port guessed from the
    # first containerPort, which is how a metrics port ends up in the iframe.
    store_pods = []
    store_svcs = []
    workloads = 0
    for off, doc in _docs(text):
        km = re.search(r"^kind:\s*[\"']?(\w+)", doc, re.M)
        if not km:
            continue
        kind = km.group(1)
        dlines = doc.split("\n")
        if kind == "Service":
            meta_path = ("metadata",)
        elif kind in POD_META_PATH:
            meta_path = POD_META_PATH[kind]
            workloads += 1
        else:
            continue
        labels = _mapping(dlines, meta_path + ("labels",)) or {}
        if labels.get(STORE_APP) != "true":
            continue
        annotations = _mapping(dlines, meta_path + ("annotations",)) or {}
        both = dict(annotations)
        both.update(labels)
        nm = re.search(r"^metadata:\s*\n(?:[ \t].*\n)*?[ \t]+name:\s*(\S+)", doc, re.M)
        what = "%s/%s" % (kind, _parse_scalar(nm.group(1)) if nm else "?")
        ln = text[:off + km.start()].count("\n") + 1
        (store_svcs if kind == "Service" else store_pods).append((what, both))
        missing = [k for k in STORE_REQUIRED if not both.get(k)]
        if both.get("embernet.ai/gui-type") == "web" and not any(
                both.get(k) for k in GUI_PORT_KEYS):
            missing.append(GUI_PORT_KEYS[0])
        if missing:
            out.append(Finding(
                path, ln, "store-label-missing",
                "%s carries %s but not %s. The dashboard reads these off the "
                "%s it lists, and without them it guesses."
                % (what, STORE_APP, ", ".join(missing),
                   "Service" if kind == "Service" else "pod")))

    # Only when the render HAS pods. An archived chart that renders nothing has
    # nothing to label, and "no pods" is not a labeling problem.
    if workloads and not store_pods:
        out.append(Finding(
            path, 1, "store-label-missing",
            "this store chart renders no pod template with %s: \"true\". The "
            "dashboard lists apps by that label on the POD, so this app installs, "
            "runs, and never shows up." % STORE_APP))
    elif (any(b.get("embernet.ai/gui-type") == "web" for _, b in store_pods)
          and not store_svcs):
        out.append(Finding(
            path, 1, "store-label-missing",
            "a web GUI pod is labeled for the store but no Service carries %s: "
            "\"true\". The subdomain route resolves the app through that "
            "Service, so the GUI has nowhere to land." % STORE_APP))
    return out


def check_file(path):
    """Return (findings, waivers). A waiver is a privileged block excused in
    writing — counted and reported, never silently dropped."""
    out = []
    waived = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError as e:
        return [Finding(path, 0, "unreadable", str(e))], [], False

    # A file that declares itself fixture data is skipped whole. Its bad values
    # are the assertions. It still counts as scanned, so the zero-files guard
    # cannot be defeated by marking everything.
    if FIXTURES_RE.search("\n".join(lines[:40])):
        return [], [], True

    text = "\n".join(lines)
    is_values = bool(VALUES_FILE_RE.search(path))

    # --- Type 3: hostNetwork demands ClusterFirstWithHostNet -----------------
    #
    # PER POD SPEC. This used to take the first hostNetwork and the first
    # dnsPolicy anywhere in the file and pair them. Helm output is one file
    # with every workload in it, so a correct dnsPolicy on workload A covered
    # for a missing one on workload B, and a wrong one on B got blamed on A.
    # The dnsPolicy that counts is the one sitting next to hostNetwork in the
    # same pod spec, which is the only place Kubernetes reads it from.
    #
    # A values file is the one exception: it is a single document of INPUTS
    # with no pod spec in it, so a wrong policy named anywhere in it is still
    # read the way it always was.
    file_pol = re.search(r"^\s*dnsPolicy:\s*(\S+)", text, re.M)
    for host_network in re.finditer(r"^\s*hostNetwork:\s*true\b", text, re.M):
        ln = text[:host_network.start()].count("\n") + 1
        idx = ln - 1
        s, e = _siblings(lines, idx)
        ind = _indent(lines[idx])
        pol = None
        for j in range(s, e):
            if _indent(lines[j]) != ind:
                continue
            pm = re.match(r"^\s*dnsPolicy:\s*(\S+)", lines[j])
            if pm:
                pol = pm.group(1).strip()
                break
        if pol is None and is_values and file_pol:
            pol = file_pol.group(1).strip()
        pol_known = pol is not None and not TEMPLATED.search(pol)
        if pol is None and not is_values:
            out.append(Finding(
                path, ln, "hostnet-dns-missing",
                "hostNetwork: true with no dnsPolicy. The pod inherits the "
                "NODE's resolv.conf and cannot resolve *.svc.cluster.local. "
                "Set dnsPolicy: ClusterFirstWithHostNet."))
        elif pol_known and pol != "ClusterFirstWithHostNet":
            extra = ""
            if pol == "ClusterFirst":
                extra = (" ClusterFirst is SILENTLY IGNORED when hostNetwork is "
                         "true — it reads correct and does nothing.")
            out.append(Finding(
                path, ln, "hostnet-dns-wrong",
                "hostNetwork: true with dnsPolicy: %s. Cluster service names "
                "will not resolve, which breaks any Ziti host.v1 targeting a "
                "service FQDN — invisibly, because the terminator still "
                "registers and TCP still connects.%s" % (pol, extra)))

    # --- Type 3: privileged instead of explicit caps -------------------------
    #
    # Kubernetes spells these WITHOUT the CAP_ prefix in capabilities.add, so a
    # test for the literal "CAP_NET_BIND_SERVICE" could never be satisfied by a
    # CORRECT manifest — only by prose that happened to contain the magic
    # string. Matching the bare name accepts the manifest spelling and the CAP_
    # form used in prose, so a chart can clear this rule by BEING right rather
    # than by adding a comment.
    #
    # EVERY occurrence, not just the first. This was re.search, so a file with
    # more than one privileged block only ever had its leading one examined --
    # and on a rendered multi-workload manifest that means every object after
    # the first was invisible, with one waived workload silencing all of them.
    # Caught by the cross-document waiver regression case.
    #
    # The capability list has to be THIS securityContext's, and it has to be
    # all three. This used to be `if "NET_BIND_SERVICE" in text: break`, so the
    # string anywhere in the file (another container, another workload, a
    # comment) waved through every privileged block in it, and a list with
    # NET_BIND_SERVICE but no NET_ADMIN or NET_RAW counted as complete. On a
    # rendered chart that is one line in one sidecar excusing the whole
    # release.
    for m in re.finditer('^\\s*privileged:\\s*true\\b', text, re.M):
        ln = text[:m.start()].count('\n') + 1
        s, e = _siblings(lines, ln - 1)
        ctx = "\n".join(_code(l) for l in lines[s:e])
        if all(re.search(r"\b(?:CAP_)?%s\b" % c, ctx) for c in CAPS_NEEDED):
            continue
        # The waiver has to be attached to the thing it waives. Scanning the
        # whole file would let one reasoned exception silence every other
        # privileged block in a values.yaml that has several.
        #
        # And it covers ONE key: the window stops at the previous privileged
        # line. Six lines is plenty of room for a second container, so without
        # this a waiver written for the PLC runtime also covered whatever
        # privileged sidecar sat under it.
        wl = lines[max(0, ln - 7):ln - 1]
        for k in range(len(wl) - 1, -1, -1):
            if re.match(r"^\s*privileged:", wl[k]):
                wl = wl[k + 1:]
                break
        window = "\n".join(wl + [lines[ln - 1]])
        #
        # Two shapes, because there are two kinds of file. In a values.yaml a
        # comment above the key is the only option, so the window is the scope.
        # In a rendered manifest comments are gone and the annotation is the
        # carrier -- scoped to the enclosing DOCUMENT, which is exactly one
        # workload, so a waiver cannot leak onto a neighbouring object.
        doc = _enclosing_doc(text, m.start())
        if WAIVER_RE.search(window) or WAIVER_ANNOTATION_RE.search(doc):
            waived.append((path, ln))
        else:
            out.append(Finding(
                path, ln, "privileged-no-caps",
                "privileged: true and no explicit capability list. Grant "
                "CAP_NET_ADMIN, CAP_NET_RAW and CAP_NET_BIND_SERVICE instead — "
                "CAP_NET_BIND_SERVICE is the one that gets forgotten, and without "
                "it the tunneler cannot bind its resolver on :53 and comes up with "
                "working interception and no name resolution. If this workload "
                "genuinely needs privileged (the flux tunnelers do — they create "
                "their own tun device, which no capability grants), waive it in "
                "writing directly above the key:\n"
                "        # app-invariants: allow-privileged — <reason>"))

    # --- Type 4: RWO PVC demands Recreate ------------------------------------
    #
    # PER DOCUMENT, AND ONLY IN REAL MANIFESTS. The first version of this rule
    # matched ReadWriteOnce anywhere in a file against RollingUpdate anywhere in
    # the same file, and immediately produced a false positive on
    # charts/fireball-site/values.yaml — which has ReadWriteMany for the main
    # workload, a ReadWriteOnce belonging to a NESTED component, and a top-level
    # strategy that has nothing to do with it.
    #
    # A values.yaml has no document structure tying a volume to a strategy, so
    # the rule cannot be decided there and is skipped rather than guessed. It is
    # decidable on a rendered manifest, where both live in one object. A check
    # that cries wolf gets switched off, which is worse than no check.
    #
    # DEPLOYMENTS ONLY. The deadlock is the surge: a Deployment starts the new
    # pod before it kills the old one, and both want the same claim. A
    # StatefulSet never surges. It takes ordinal N down, then brings ordinal N
    # back on N's own claim from volumeClaimTemplates, so RollingUpdate is the
    # normal, correct way to run one. This used to match StatefulSet too, which
    # failed every HA database the moment its HA mode got rendered.
    for off, doc in _docs(text):
        if not re.search(r"^\s*kind:\s*[\"']?Deployment\b", doc, re.M):
            continue
        if "ReadWriteOnce" not in doc:
            continue
        strat = re.search(r"^\s*type:\s*RollingUpdate\b", doc, re.M)
        if strat:
            ln = text[:off + strat.start()].count("\n") + 1
            out.append(Finding(
                path, ln, "rwo-rollingupdate",
                "ReadWriteOnce PVC with strategy RollingUpdate in the same "
                "object. The surge pod can never attach the volume; the upgrade "
                "deadlocks on Multi-Attach and the release lands failed while "
                "the spec is fine. Use strategy: Recreate."))

    out.extend(_check_rendered(path, text))

    # --- Types 1/2: intercept addressing -------------------------------------
    # Python docstrings are prose, and prose is already exempt — whole-line `#`
    # comments are skipped just below, and a docstring is the same thing with
    # different punctuation. The rule is that this checker reads DECLARATIONS,
    # not narrative.
    #
    # It matters here because the good scripts explain the incidents that
    # produced these rules, and the explanation has to name the address to mean
    # anything: wire-k3s-api-services.py says "fragua-k3s-api was pinned at
    # 100.65.1.1, and once it gained a .flux.internal name the router handed it
    # 100.65.0.2". Flagging that is telling the author to delete the only record
    # of why the rule exists. An intercept in CODE is still caught — see the
    # must-fail fixtures in test-check-app-invariants.py.
    in_docstring = None
    is_py = path.endswith(".py")

    current_key = ""
    ctx = []  # (indent key, lowered code) of the lines enclosing this one
    for i, line in enumerate(lines, 1):
        if is_py:
            rest = line
            while True:
                if in_docstring:
                    end = rest.find(in_docstring)
                    if end < 0:
                        rest = ""
                        break
                    rest = rest[end + 3:]
                    in_docstring = None
                    continue
                nxt = min((p for p in (rest.find('"""'), rest.find("'''")) if p >= 0),
                          default=-1)
                if nxt < 0:
                    break
                in_docstring = rest[nxt:nxt + 3]
                rest = rest[nxt + 3:]
            # `rest` is whatever on this line was OUTSIDE a docstring.
            if not rest.strip():
                continue
            line = rest
        if line.lstrip().startswith("#"):
            continue
        # Track which lines this one is nested under, by indentation, so the
        # node-range rule can ask "is this literal declared AS an intercept".
        # A list item counts as a child of a key at its own indent, which is
        # legal YAML ("addresses:" then "- 100.64.1.7" in the same column).
        code_l = re.sub(r"\s+#.*$", "", line).lower()
        eff = 2 * (len(line) - len(line.lstrip())) + (1 if line.lstrip().startswith("- ") else 0)
        while ctx and ctx[-1][0] >= eff:
            ctx.pop()
        in_intercept = "intercept" in code_l or any("intercept" in c for _, c in ctx)
        ctx.append((eff, code_l))
        # Track the key a list item belongs to, so a certificate SAN list is not
        # read as an addressing declaration. Only mapping keys reset this; list
        # items ("- 100.64.2.2") inherit the key above them, which is exactly
        # the shape a tls-san block has.
        km = KEY_RE.match(line)
        if km:
            current_key = (km.group(1) or km.group(2) or "").lower()
        if current_key in SAN_KEYS:
            continue
        # Whole-line comments are skipped just above; strip INLINE comments here
        # for the same reason. Documenting the ranges you must avoid is not the
        # same as intercepting one — flux-edge-tunnel's values.yaml annotates
        # both 100.64.0.0/24 and 100.65.0.0/16 in a trailing comment, and
        # flagging that meant the chart could not describe its own arguments.
        stripped = TEMPLATED.sub("", re.sub(r"\s+#.*$", "", line))
        for m in DNS_POOL_RE.finditer(stripped):
            out.append(Finding(
                path, i, "intercept-in-dns-pool",
                "%s is inside the router's DNS intercept pool 100.65.0.0/16. "
                "The tunneler allocates from that range, so this address can be "
                "handed to another service and the path goes silently dead. Use "
                "a <svc>.flux.internal name and let the router allocate."
                % m.group(0)))
        # Only a literal DECLARED as an intercept: on a line that names one
        # (INTERCEPT_ADDR = ..., "intercept": ..., intercept.v1 '{"addresses":
        # [...]}') or nested under one (intercept: / addresses: / - ...). This
        # used to fire on any node address in any file where the word
        # "intercept" appeared at all, comments included, so the dashboard's
        # k3s.serverURL (a node the agent dials, which is exactly what a node
        # address is for) failed because an OAuth comment 800 lines up said "a
        # code intercepted between Vord and the callback".
        for m in NODE_RANGE_RE.finditer(stripped):
            if not in_intercept:
                continue
            out.append(Finding(
                path, i, "intercept-shadows-node",
                "%s lies in a node address range. Intercepting a real machine's "
                "address installs it on lo on every dialer and severs the direct "
                "path to that machine." % m.group(0)))

    return out, waived, False


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2

    findings = []
    waivers = []
    scanned = 0
    fixtures = 0
    per_root = []
    for root in argv[1:]:
        if not os.path.exists(root):
            print("no such path: %s" % root, file=sys.stderr)
            return 2
        n = 0
        for f in scan_files(root):
            n += 1
            f_out, f_waived, f_fixture = check_file(f)
            findings.extend(f_out)
            waivers.extend(f_waived)
            fixtures += 1 if f_fixture else 0
        per_root.append((root, n))
        scanned += n

    # A check that silently scans nothing is worse than no check — it reports
    # success forever. Same failure the dashboard's inline-JS gate hit.
    #
    # PER ROOT, not just in total. A sweep like `check ... cluster charts
    # templates` where ONE argument is stale still scans plenty of files, so a
    # total-only guard passes while a whole tree goes unread — which is exactly
    # how the `charts` prune stayed invisible. Name the empty root and fail.
    empty = [r for r, n in per_root if n == 0]
    if empty:
        print("app-invariants: these paths matched 0 files — wrong path? "
              "refusing to pass: %s" % ", ".join(empty), file=sys.stderr)
        return 2
    if scanned == 0:
        print("app-invariants: scanned 0 files — wrong path? refusing to pass.",
              file=sys.stderr)
        return 2

    # Waivers are REPORTED, always, pass or fail. An exception that stops being
    # visible stops being an exception and becomes the new default — which is
    # how `privileged: true` spread across the fleet in the first place.
    def report_waivers():
        if not waivers:
            return
        print("\napp-invariants: %d privileged waiver(s) in force:" % len(waivers))
        for p, ln in waivers:
            print("  %s:%d" % (p, ln))

    # Fixture files are declared, not inferred, so say how many were skipped.
    # A silent skip is how a whole tree stops being checked without anyone
    # noticing — the same shape as the `charts` prune bug.
    tally = "%d file(s) scanned" % scanned
    if fixtures:
        tally += " (%d declared fixtures, skipped)" % fixtures

    if not findings:
        print("app-invariants: %s; 0 violations" % tally)
        report_waivers()
        return 0

    print("app-invariants: %s; %d violation(s)\n" % (tally, len(findings)))
    for f in findings:
        print(f)
    report_waivers()
    print("\nSee templates/app/README.md for why each of these exists.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
