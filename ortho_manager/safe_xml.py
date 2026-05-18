import re
import xml.etree.ElementTree as _ET

_FORBIDDEN_XML_MARKUP = re.compile(br"<!\s*(DOCTYPE|ENTITY)\b", re.IGNORECASE)


def parse_vrt_xml(path):
    """Parse OrthoManager VRT XML after rejecting DTD/entity declarations."""
    with open(path, "rb") as handle:
        data = handle.read()
    if _FORBIDDEN_XML_MARKUP.search(data):
        raise ValueError("Unsafe XML markup is not allowed in VRT files")

    parser_factory = getattr(_ET, "XMLParser")
    tree_builder_factory = getattr(_ET, "TreeBuilder")
    parser = parser_factory(target=tree_builder_factory())
    parser.feed(data)
    root = parser.close()
    return _ET.ElementTree(root)
