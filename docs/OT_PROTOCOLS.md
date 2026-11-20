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
| DNP3 | `dnp3` | server (outstation) | TCP 20000 | 4.7.0 |
| DNP3 | `dnp3_master` | client (polling master) | outbound to the outstation's 20000 | 4.7.0 |
| IEC 60870-5-104 | `iec104` | server (controlled station) | TCP 2404 | 4.7.0 |
| IEC 60870-5-104 | `iec104_master` | client (controlling station) | outbound to the station's 2404 | 4.7.0 |
| IEC 61850 GOOSE | `goose` | publisher (layer 2 multicast) | Ethernet 0x88B8 | 4.8.0 |
| IEC 61850 GOOSE | `goose_subscriber` | subscriber (layer 2) | Ethernet 0x88B8 | 4.8.0 |
| PROFINET DCP and RT | `profinet` | device (DCP responder, RT cyclic producer) | Ethernet 0x8892 | 4.8.0 |
| EtherCAT | `ethercat` | slaves (process data RAM, AL state machine, SII, FMMU) | Ethernet 0x88A4 | 4.8.0 |
| EtherCAT | `ethercat_master` | master (bus bring-up and cyclic LRW) | Ethernet 0x88A4 | 4.8.0 |

The slices still to come: the PROFINET IO connection manager (the DCE/RPC Connect
that sets up an application relationship), Omron FINS, GE SRTP, HART-IP, IEC 61850
MMS, C37.118, and Modbus RTU over TCP.

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
pip install dnp3py && python test_dnp3.py         # 4/4
python test_iec104.py                             # 4/4
sudo python test_goose.py                         # 2/2 (veth pair, root)
sudo python test_profinet.py                      # 2/2
sudo python test_ethercat.py                      # 2/2
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

## DNP3

```json
"dnp3": { "enabled": true, "port": 20000, "address": 10, "master_address": 0,
          "analog_scale": 100, "analog_deadband": 0.5,
          "tag_mapping": { "Count": { "type": "counter" }, "Valve": { "type": "binary_output" },
                           "Setpoint": { "type": "analog_output", "scale": 10 },
                           "Temperature": { "class": 2, "index": 4 } } }
```

One outstation. A float or int tag is an Analog Input (group 30), a bool a Binary
Input (group 1); `tag_mapping` types are `binary_input`, `analog_input`,
`counter`, `binary_output` and `analog_output`, with `index`, `class` (1, 2 or 3)
and `deadband`. A change beyond the deadband is a change event in its class, read
by a class poll. Outputs take select-before-operate and direct operate (CROB, group
12, and analog output, group 41) and the control writes the tag; a control to a
point that is not an output is refused.

Analog values go out as 32-bit integers (dnp3py serves g30v1 and g40v2), so a
float is sent as value times `scale` (100 by default, two decimals); the master
divides it back out, as it does with a real RTU. `dnp3_master` is the polling side:
`{"host": "...", "port": 20000, "address": 1, "outstation_address": 10,
"interval": 5}` does an integrity poll and a class poll every interval and keeps
what it reads. It sends no control.

The stack is dnp3py (MIT, pure Python, IEEE 1815-2012 Level 2). Not simulated:
secure authentication, file transfer, double-bit inputs, serial or UDP transport.
`test_dnp3.py` is the check (integrity poll, class 1 event, controls, the master
role).

## IEC 60870-5-104

```json
"iec104": { "enabled": true, "port": 2404, "common_address": 1, "deadband": 0.5,
            "cyclic_seconds": 0, "select_before_operate": false,
            "tag_mapping": { "Count": { "type": "counter" },
                             "Valve": { "type": "command" }, "Temperature": { "ioa": 3100 } } }
```

A controlled station. A bool tag is M_SP_NA_1 (IOA from 1), an int tag M_ME_NB_1
scaled (from 2001), a float tag M_ME_NC_1 short float (from 3001), a `counter`
M_IT_NA_1 (from 4001); a `command` tag is also controllable (from 5001): a bool by
C_SC_NA_1, a float by C_SE_NC_1, an int by C_SE_NB_1, with select and execute, and
the command writes the tag. It does STARTDT, STOPDT and TESTFR, answers station
interrogation (COT 20) and counter interrogation (COT 37), reports changes
spontaneously (COT 3) with CP56Time2a time tags once data transfer is started,
optionally reports cyclically (COT 1), confirms clock synchronisation, test and
reset process commands, and answers an unknown type, common address or IOA with the
negative confirmations (COT 44, 46 and 47). Flow control follows k=12 and w=8, and
an idle link is probed after t3 (20 s). `iec104_master` is the controlling
station: it does STARTDT, a station and a counter interrogation every `interval`,
and with `tag_map` sends a tag's value to an IOA as a command.

There is no permissive library for this protocol (the Python ones are GPLv3), so it
is written from IEC 60870-5-104 and IEC 60870-5-101 (the standard's sections are
named in `protocols/iec104.py`). `test_iec104.py` uses a hand written raw client
that does not import the simulator's codec, starting from the byte sequences in the
standard's examples. Not simulated: double-point and step position information,
bitstrings, file transfer, parameter commands, TLS (IEC 62351-3), and the t1
timeout on a silent peer.

## Layer 2 protocols (GOOSE, PROFINET, EtherCAT)

These send and receive raw Ethernet frames, so they need `CAP_NET_RAW`, and they see
only the Ethernet segment of the interface they bind (`interface`, default the first
one that is up). In Kubernetes that is the pod's own link: other pods on the node
bridge see the frames. To put them on a plant segment run the pod with
`network.hostNetwork: true` and name the node's interface.

The chart carries `NET_RAW` while any of them is enabled. A Kubernetes non-root
process gets no ambient capability, so a capability added to a non-root container
never reaches it; the container therefore runs as root with every capability
dropped except `NET_RAW` and privilege escalation off, only while one of these is
enabled (`needsRawSockets` in `_helpers.tpl`). With none enabled the container is
non-root with all capabilities dropped, as before. Files the root container writes to
the data volume are owned by root; if you turn the layer 2 protocols off again, the
non-root container cannot rewrite them (the database and tag store), so recreate the
volume or `chown -R 1000:1000` it first. Outside Kubernetes run as root
or `setcap cap_net_raw+ep` the Python binary.

### GOOSE

`goose` publishes the `tags` as a GOOSE data set (a bool is BOOLEAN, an int INTEGER, a
float FLOAT32, a string VISIBLE-STRING) to `dest_mac` (default 01:0C:CD:01:00:01),
with APPID, gocbRef, datSet, goID and confRev from the config. The first frame is
stNum 1 sqNum 0; on a change stNum increases, sqNum restarts at 0, and the frame is
repeated at `min_time_ms`, doubling to `max_time_ms`, which is the heartbeat;
timeAllowedtoLive is twice that. Frames carry an 802.1Q tag (priority 4).
`goose_subscriber` receives a control block (`gocb_ref`) and writes entry i into
`tags[i]` on each new stNum. Not simulated: Sampled Values, R-GOOSE, IEC 62351-6.
`test_goose.py` reads the frames with a decoder written in the test.

### PROFINET

`profinet` answers DCP Identify (All, NameOfStation, and device ID filters), Get,
and Set of the name, IP and Signal with the name, vendor, device and vendor ID,
role, options, MAC and IP block set. With `controller_mac` and `tags` it sends
Class 1 RT frames (FrameID `frame_id`, default 0xC000, VLAN priority 6) every
`cycle_ms` with the tag values as IO data, the cycle counter (1/32 ms), data status
0x35 and transfer status 0. **Not done: the IO connection manager** (DCE/RPC
Connect, Control, Release on UDP 34964), acyclic records, alarms, LLDP, MRP, IRT. The
RT frame is device traffic for an analyzer or intrusion detection; a controller
cannot set up an application relationship with it yet. `test_profinet.py` is the
check, with a hand written DCP client.

### EtherCAT

`ethercat` is `slave_count` (1 to 8) slaves with a 4 KiB register space and process
RAM: the ESC type registers, station address, DL status, the AL state machine (INIT,
PRE-OP, SAFE-OP, OP, with the error bit and status code 0x0011 or 0x001E), the SII
identity (vendor, product, revision, serial), and FMMUs and SyncManagers that the
master configures and that decide how LRD, LWR and LRW reach the process data. The
working counter follows the standard. `tags_in` go to the master (REAL32, INT32 or a
byte, from 0x1100) and `tags_out` come from it into the tag store. `ethercat_master`
brings a bus up (scan, addresses, SII, FMMU and SyncManager setup, INIT to OP) and runs
a cyclic LRW. Not simulated: distributed clocks, CoE, FoE, EoE, ring topology.
`test_ethercat.py` uses a hand written master.

### Standards and sources

The wire format is written against ODVA's CIP Networks Library Volume 1 (CIP)
and Volume 2 (EtherNet/IP encapsulation, common packet format) and Rockwell's
Logix 5000 Controllers Data Access manual (1756-PM020). No library implements
the server side under a license EmberBurn can use: cpppo is GPLv3 or
proprietary. pycomm3 is used only as the test client.
