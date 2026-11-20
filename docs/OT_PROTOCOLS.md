# OT protocol simulators

EmberBurn serves its tags as the device traffic of industrial protocols, for
testing protocol analyzers, intrusion detection and clients, and for demos. Each
protocol is a publisher under `publishers.<key>` in the config, off by default,
started next to the existing OPC UA, Modbus TCP and MQTT publishers. Tags,
simulation modes and the web UI work as they always have; the protocol is
another way to read them.

The code is in the `protocols/` package. A protocol is loaded only when it is
enabled.

| Protocol | Config key | Role | Ports | Status |
|---|---|---|---|---|
| EtherNet/IP and CIP | `ethernet_ip` | server (Logix style controller, implicit I/O producer and consumer) | TCP and UDP 44818, UDP 2222 | 4.5.0 |
| EtherNet/IP and CIP | `ethernet_ip_client` | client (writes tags to, and polls tags from, a controller) | outbound to the target's 44818 | 4.5.0 |
| S7comm | `s7comm` | server (Siemens S7 CPU, tags in data blocks) | TCP 102 | 4.6.0 |
| BACnet/IP | `bacnet` | server (one device, one object per tag) | UDP 47808 | 4.6.0 |

The slices still to come, in this order: DNP3, IEC 60870-5-104,
then PROFINET (DCP, RT and IO-CM), EtherCAT, Omron FINS, GE SRTP, HART-IP, IEC 61850
(MMS and GOOSE), C37.118, and Modbus RTU over TCP. Layer 2 protocols (PROFINET
DCP and RT, EtherCAT, GOOSE) need raw sockets, so the container and chart will
carry `NET_RAW` for them when they ship.

## EtherNet/IP and CIP

Config (`config/config_ethernet_ip.json` is a working example):

```json
"ethernet_ip": {
  "enabled": true,
  "host": "0.0.0.0",
  "port": 44818,
  "io_port": 2222,
  "program_name": "EmberBurn",
  "identity": { "vendor_id": 1, "device_type": 14, "product_code": 166,
                "revision_major": 33, "revision_minor": 11, "product_name": "1756-L83E/B" },
  "tag_mapping": { "Temperature": { "name": "Temp", "type": "REAL" } },
  "assembly_input_tags": ["Temperature", "Pressure", "Counter"],
  "assembly_output_tags": ["Setpoint"],
  "assembly_output_size": 32
}
```

What it speaks:

- Encapsulation on TCP 44818: RegisterSession, UnRegisterSession, SendRRData,
  SendUnitData, ListIdentity, ListServices, ListInterfaces, NOP. ListIdentity,
  ListServices and ListInterfaces also answer on UDP 44818, including broadcast.
- Logix tag services: Read Tag (0x4C), Read Tag Fragmented (0x52), Write Tag
  (0x4D) and Write Tag Fragmented (0x53), by symbol or by Symbol Object
  instance id, and Multiple Service Packet (0x0A). A write goes back into the
  gateway's tag store, so a simulated tag takes the value until its next scan.
- Tag browse through the Symbol Object (Get Instance Attribute List 0x55), and
  the built in STRING template (Template Object 0x6C), so a Logix client uploads
  the tag list and reads strings.
- Identity (class 0x01), Message Router (0x02), Program name (0x64), Assembly
  (0x04, instances 100 and 101), Connection Manager (0x06): Unconnected Send,
  Forward Open, Large Forward Open, Forward Close.
- Connected explicit messaging (class 3) and implicit I/O (class 1): the target
  produces Assembly 100 to the originator's UDP port at the T to O RPI, point
  to point or multicast, and consumes Assembly 101 on UDP `io_port`.

Types: a `float` tag is a REAL, `int` a DINT, `bool` a BOOL and `string` a STRING
(the Logix 82 character structure). `tag_mapping` overrides the symbol name and
the CIP type (BOOL, SINT, INT, DINT, LINT, REAL, LREAL, STRING). A tag name such
as `Plant/Line1/Temperature` is served as the symbol `Plant_Line1_Temperature`,
since a Logix symbol cannot contain a slash.

Assembly 100 packs the numeric and boolean tags, 32 bit values on 4 byte
offsets, in the order of `assembly_input_tags` when it is set and in the order
tags are first seen otherwise. Set the list to fix the layout across restarts.
Assembly 101 is a plain byte image of `assembly_output_size` bytes; with
`assembly_output_tags` its bytes are written back into those tags.

The identity defaults to a ControlLogix 1756-L83E, because that is what
EtherNet/IP tooling expects to meet. Change `identity` to present any other
device. This is a simulator, and the identity does not change that: nothing it
serves comes from a real controller.

Not simulated: arrays and user defined structures other than STRING, program
scoped tags, the PCCC and Micro800 paths, CIP Safety, CIP Security, and
EtherNet/IP over a serial or DLR ring.

### Client role

`publishers.ethernet_ip_client` makes EmberBurn the scanner: it uploads the
target's tag list, writes the EmberBurn tags named in `tag_map` into the target's
tags every `interval` seconds, and reads `poll_tags` back. The target can be a
real controller or another EmberBurn.

```json
"ethernet_ip_client": {
  "enabled": true, "host": "plc.plant.example", "slot": 0, "interval": 2.0,
  "tag_map": { "Plant/Line1/Temperature": "Line1_Temp" },
  "poll_tags": ["Line1_Setpoint"]
}
```

It uses pycomm3 (MIT). It connects out only, so the chart adds no port for it.

### Chart

`config.publishers.ethernet_ip.enabled: true` adds the container ports
(`enip-tcp`, `enip-udp`, `enip-io`) and a `<release>-ot` Service carrying them.
All ports are above 1024, so the container's non-root, all capabilities dropped
context is unchanged. The optional NetworkPolicy gains a matching ingress rule.

### Proof

`test_enip.py` is the check. It drives the server with pycomm3 (MIT), an
independent client, through the full Logix path (identity, program name, tag
list, STRING template, multi tag read, write, discovery) and with raw
encapsulation for ListServices, implicit I/O over UDP including the O to T
direction, Forward Close, and the error paths. The same run is captured with
tshark: every frame decodes as ENIP, CIP, CIP I/O with no malformed or expert
error.

```
pip install pycomm3
python test_enip.py     # 4/4
pip install python-snap7 && python test_s7.py     # 2/2
pip install bacpypes3 && python test_bacnet.py    # 2/2
```

## S7comm

```json
"s7comm": { "enabled": true, "port": 102, "db": 1, "db_size": 1024, "dbs": [2],
            "string_length": 32,
            "tag_mapping": { "Temperature": { "db": 1, "offset": 0, "type": "REAL" },
                             "Run": { "db": 1, "offset": 8, "bit": 0, "type": "BOOL" } } }
```

Tags are placed in data block `db` in the order they are first seen, or at the
`offset` (and `bit`) given in `tag_mapping`. REAL and DINT are 4 bytes, INT 2,
LREAL 8, all big endian; BOOLs share bytes bit by bit; a STRING is the S7 string
(max length, length, characters). A float tag is a REAL, an int a DINT, a bool a
BOOL, a string a STRING. A client write to a data block goes back into the tag
store. `dbs` lists extra data blocks to serve. The server is python-snap7 (MIT),
whose CPU identity is an S7-300; the module maps data block bytes to tags.

Port 102 is below 1024. The chart sets the pod sysctl
`net.ipv4.ip_unprivileged_port_start=0` while it is enabled, so the container
stays non-root with every capability dropped. Outside Kubernetes, set `port` above
1024 or give the process the privilege.

Not simulated: PLC programming functions (block upload and download, run and
stop control), the S7comm-plus protocol of S7-1200 and S7-1500 (a different
protocol on the same port), and anything but data blocks as memory areas.
`test_s7.py` is the check: a snap7 client reads every type, sees a live change,
writes, and the write reaches the tag store.

## BACnet/IP

```json
"bacnet": { "enabled": true, "host": "0.0.0.0", "port": 47808, "prefix": 24,
            "device_instance": 1234, "device_name": "EmberBurn",
            "tag_mapping": { "Temperature": { "units": "degreesCelsius", "instance": 10 } } }
```

One BACnet device on UDP 47808. A float or int tag is an Analog Value, a bool a
Binary Value, a string a Character String Value; `tag_mapping` sets `type`
(`AV`, `BV`, `CSV`), `instance`, `name`, `description` and `units`. Who-Is and
I-Am, ReadProperty, ReadPropertyMultiple, WriteProperty and the object list work,
and a WriteProperty reaches the tag store. `host` 0.0.0.0 means the pod's primary
address, and `prefix` sets its broadcast domain, so Who-Is broadcasts on that
subnet find it. The stack is bacpypes3 (MIT).

Not simulated: COV subscriptions, alarms and events, schedules, trend logs,
BACnet/SC, and routing between networks. `test_bacnet.py` is the check: a
bacpypes3 client discovers the device, reads the object list and each object
type, sees a live change and writes.

### Standards and sources

The wire format is written against ODVA's CIP Networks Library Volume 1 (CIP)
and Volume 2 (EtherNet/IP encapsulation, common packet format) and Rockwell's
Logix 5000 Controllers Data Access manual (1756-PM020). No library implements
the server side under a license EmberBurn can use: cpppo is GPLv3 or
proprietary. pycomm3 is used only as the test client.
