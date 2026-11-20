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
    "s7comm": ("protocols.s7", "S7CommPublisher"),
    "bacnet": ("protocols.bacnet", "BACnetPublisher"),
    "iec104": ("protocols.iec104", "IEC104Publisher"),
    "iec104_master": ("protocols.iec104", "IEC104MasterPublisher"),
    "dnp3": ("protocols.dnp3", "DNP3Publisher"),
    "dnp3_master": ("protocols.dnp3_master", "DNP3MasterPublisher"),
    "ethernet_ip_client": ("protocols.enip_client", "EtherNetIPClientPublisher"),
}

# Display names and card descriptions for the web UI, keyed by class name with
# the 'Publisher' suffix stripped (the same contract as
# PublisherManager.PUBLISHER_DISPLAY_NAMES).
DISPLAY_NAMES = {
    "EtherNetIP": "EtherNet/IP",
    "EtherNetIPClient": "EtherNet/IP Client",
    "S7Comm": "S7comm",
    "BACnet": "BACnet/IP",
    "IEC104": "IEC 104",
    "IEC104Master": "IEC 104 Master",
    "DNP3": "DNP3",
    "DNP3Master": "DNP3 Master",
}

DESCRIPTIONS = {
    "EtherNet/IP": "Serves tags as a Logix style EtherNet/IP and CIP device on TCP and UDP 44818, with implicit I/O on UDP 2222",
    "S7comm": "Serves tags as data block variables of a Siemens S7 CPU over ISO on TCP 102",
    "BACnet/IP": "Serves tags as Analog, Binary and Character String Value objects of a BACnet/IP device on UDP 47808",
    "IEC 104": "Serves tags as information objects of an IEC 60870-5-104 controlled station on TCP 2404",
    "IEC 104 Master": "Polls a remote IEC 60870-5-104 station with station and counter interrogation",
    "DNP3": "Serves tags as points of a DNP3 outstation on TCP 20000, with events and controls",
    "DNP3 Master": "Polls a remote DNP3 outstation with integrity and class polls",
    "EtherNet/IP Client": "Writes tags to, and polls tags from, a remote EtherNet/IP controller",
}
