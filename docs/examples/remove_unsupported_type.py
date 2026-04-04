"""package.xml から取得不可能なメタデータタイプを削除するスクリプト。

Usage: python3 remove_unsupported_type.py <package.xml> <TypeName>
"""
import sys
import xml.etree.ElementTree as ET

if len(sys.argv) != 3:
    print("Usage: python3 remove_unsupported_type.py <package.xml> <TypeName>", file=sys.stderr)
    sys.exit(2)

pkg, type_name = sys.argv[1], sys.argv[2]
NS = "http://soap.sforce.com/2006/04/metadata"
ET.register_namespace("", NS)

tree = ET.parse(pkg)
root = tree.getroot()
tag = "{%s}types" % NS
name_tag = "{%s}name" % NS

to_remove = [
    t for t in root.findall(tag)
    if t.find(name_tag) is not None and t.find(name_tag).text == type_name
]
for t in to_remove:
    root.remove(t)

print("Removed %d block(s) for type: %s" % (len(to_remove), type_name))
tree.write(pkg, xml_declaration=True, encoding="UTF-8")
