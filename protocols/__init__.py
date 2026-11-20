"""Simulated OT protocol endpoints for EmberBurn.

Each module in here is one protocol: a publisher the PublisherManager starts
next to the existing Modbus, OPC UA and MQTT ones, serving the gateway's tags as
that protocol's native objects so a client, a protocol analyzer or an intrusion
detection system sees realistic device traffic.

The PublisherManager imports this package lazily and only for protocols that are
enabled, so a protocol's dependency is never loaded for an install that does not
use it. REGISTRY maps the publisher config key to (module, class).
"""

REGISTRY = {
    "ethernet_ip": ("protocols.enip", "EtherNetIPPublisher"),
    "ethernet_ip_client": ("protocols.enip_client", "EtherNetIPClientPublisher"),
}

# Display names and card descriptions for the web UI, keyed by class name with
# the 'Publisher' suffix stripped (the same contract as
# PublisherManager.PUBLISHER_DISPLAY_NAMES).
DISPLAY_NAMES = {
    "EtherNetIP": "EtherNet/IP",
    "EtherNetIPClient": "EtherNet/IP Client",
}

DESCRIPTIONS = {
    "EtherNet/IP": "Serves tags as a Logix style EtherNet/IP and CIP device on TCP and UDP 44818, with implicit I/O on UDP 2222",
    "EtherNet/IP Client": "Writes tags to, and polls tags from, a remote EtherNet/IP controller",
}
