"""CryEngine binary XML (CryXmlB) -> xml.etree.ElementTree.Element. Plain text XML is parsed as is."""
import struct
import xml.etree.ElementTree as ET


def parse(data: bytes) -> ET.Element:
    if not data.startswith(b"CryXmlB"):
        return ET.fromstring(data.decode("utf-8", "replace").lstrip("﻿"))
    _, node_off, node_cnt, attr_off, attr_cnt, child_off, child_cnt, str_off, str_size = struct.unpack_from("<9I", data, 8)
    strings = data[str_off:str_off + str_size]

    def s(o):
        return strings[o:strings.index(b"\0", o)].decode("utf-8", "replace")

    nodes = [struct.unpack_from("<IIHHIIII", data, node_off + 28 * i) for i in range(node_cnt)]
    attrs = [struct.unpack_from("<II", data, attr_off + 8 * i) for i in range(attr_cnt)]
    children = [struct.unpack_from("<I", data, child_off + 4 * i)[0] for i in range(child_cnt)]

    def build(i):
        tag, content, n_attr, n_child, _parent, first_attr, first_child, _ = nodes[i]
        el = ET.Element(s(tag), {s(attrs[first_attr + j][0]): s(attrs[first_attr + j][1]) for j in range(n_attr)})
        if content:
            el.text = s(content)
        for j in range(n_child):
            el.append(build(children[first_child + j]))
        return el

    return build(0)
