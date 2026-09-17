"""VRT parsing with encoding-aware rejection of DTDs and entity declarations."""
import xml.etree.ElementTree as _ET  # nosec B405 # tree construction only; Expat below rejects DTDs/entities.
from xml.parsers import expat


def _reject_declaration(*args):
    raise ValueError('Unsafe XML markup is not allowed in VRT files')


def _expanded_name(name):
    return '{' + name if '}' in name else name


def parse_vrt_xml(path):
    """Build an ElementTree without resolving entities, including UTF-16 input."""
    builder = _ET.TreeBuilder()
    parser = expat.ParserCreate(namespace_separator='}')
    parser.StartDoctypeDeclHandler = _reject_declaration
    parser.EntityDeclHandler = _reject_declaration
    parser.ExternalEntityRefHandler = _reject_declaration
    parser.StartElementHandler = lambda name, attrs: builder.start(
        _expanded_name(name), {_expanded_name(k): v for k, v in attrs.items()})
    parser.EndElementHandler = lambda name: builder.end(_expanded_name(name))
    parser.CharacterDataHandler = builder.data
    try:
        with open(path, 'rb') as handle:
            parser.ParseFile(handle)
    except expat.ExpatError as error:
        raise _ET.ParseError(str(error)) from error
    return _ET.ElementTree(builder.close())
