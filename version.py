"""Single source of truth for the EmberBurn application version.

setup.py, the REST API index payload and anything else that reports a version
read from here. Previously setup.py carried its own hardcoded string, which
drifted to 4.0.7 while the released chart was on 4.1.3.

Keep this in sync with the git tag and with helm/opcua-server/Chart.yaml's
`appVersion` when cutting a release.
"""

__version__ = "4.1.15"
