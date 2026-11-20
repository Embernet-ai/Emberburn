"""Layer 2 access for the Ethernet protocols (PROFINET, EtherCAT, GOOSE).

AF_PACKET raw sockets need the NET_RAW capability, and see only the Ethernet
segment of the interface they are bound to. In Kubernetes that is the pod's own
virtual link (frames reach other pods on the same node bridge). To put frames on a
plant segment run the pod with `network.hostNetwork: true` and name the node's
interface in the protocol's `interface` setting. The chart adds NET_RAW when a
layer 2 protocol is enabled (see docs/OT_PROTOCOLS.md).
"""
import fcntl
import os
import socket
import struct
from typing import List, Optional

ETH_P_ALL = 0x0003
SIOCGIFINDEX = 0x8933
PACKET_ADD_MEMBERSHIP = 1
PACKET_MR_MULTICAST = 0
SOL_PACKET = 263


def mac_bytes(mac: str) -> bytes:
    return bytes(int(x, 16) for x in mac.replace("-", ":").split(":"))


def mac_str(b: bytes) -> str:
    return ":".join(f"{x:02x}" for x in b)


def pick_interface(wanted: Optional[str] = None) -> str:
    """The configured interface, else the first one that is up and not loopback."""
    names = sorted(os.listdir("/sys/class/net"))
    if wanted:
        if wanted not in names:
            raise OSError(f"interface {wanted} not found (have {', '.join(names)})")
        return wanted
    for n in names:
        if n == "lo":
            continue
        try:
            with open(f"/sys/class/net/{n}/operstate") as f:
                state = f.read().strip()
        except OSError:
            continue
        if state in ("up", "unknown"):
            return n
    raise OSError("no usable network interface")


class RawInterface:
    """A raw Ethernet socket bound to one interface."""

    def __init__(self, ifname: Optional[str] = None, ethertypes: Optional[List[int]] = None):
        self.name = pick_interface(ifname)
        self.sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
        self.sock.bind((self.name, 0))
        with open(f"/sys/class/net/{self.name}/address") as f:
            self.mac = mac_bytes(f.read().strip())
        self.index = socket.if_nametoindex(self.name)
        self.ethertypes = set(ethertypes or [])
        self.sock.settimeout(0.2)

    def join(self, mac: str):
        """Receive frames sent to this multicast MAC."""
        mreq = struct.pack("iHH8s", self.index, PACKET_MR_MULTICAST, 6, mac_bytes(mac) + b"\x00\x00")
        self.sock.setsockopt(SOL_PACKET, PACKET_ADD_MEMBERSHIP, mreq)

    def send(self, frame: bytes):
        self.sock.send(frame if len(frame) >= 60 else frame + bytes(60 - len(frame)))

    def recv(self) -> Optional[bytes]:
        """The next frame of a wanted ethertype (VLAN tagged frames are matched on the
        inner type), or None on timeout. Frames this interface sent are skipped."""
        try:
            frame, addr = self.sock.recvfrom(4096)
        except socket.timeout:
            return None
        except OSError:
            return None
        if addr[2] == socket.PACKET_OUTGOING:
            return None
        if self.ethertypes and ethertype(frame) not in self.ethertypes:
            return None
        return frame

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def ethertype(frame: bytes) -> int:
    if len(frame) < 14:
        return 0
    et = struct.unpack_from(">H", frame, 12)[0]
    if et == 0x8100 and len(frame) >= 18:
        et = struct.unpack_from(">H", frame, 16)[0]
    return et


def payload_offset(frame: bytes) -> int:
    return 18 if len(frame) >= 18 and struct.unpack_from(">H", frame, 12)[0] == 0x8100 else 14
