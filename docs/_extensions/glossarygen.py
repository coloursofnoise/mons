import textwrap

from docutils import nodes
from docutils.statemachine import StringList
from sphinx.application import Sphinx
from sphinx.domains.std import Glossary


class NodeReprVisitor(nodes.NodeVisitor):
    content_indent = "   "

    def __init__(self, document):
        super().__init__(document)
        self.content = ""
        self.indent = 0

    def visit_bullet_list(self, node):
        self.bullet = node["bullet"]
        self.content += "\n"
        self.indent += 1

    def depart_bullet_list(self, node):
        self.content += "\n"
        self.indent -= 1

    def visit_list_item(self, node):
        self.content += f"{self.content_indent*self.indent} {self.bullet} "

    def visit_paragraph(self, node):
        self.content += node.astext() + "\n\n"

    def unknown_visit(self, node):
        pass

    def unknown_departure(self, node):
        pass


class GlossaryGen(Glossary):
    def run(self) -> list[nodes.Node]:
        def parse_content(node: nodes.Node):
            assert node.document
            visitor = NodeReprVisitor(node.document)
            node.walkabout(visitor)
            return visitor.content

        node = nodes.Element()
        self.state.nested_parse(
            self.content, self.content_offset, node, match_titles=True
        )

        parsed_content = [""]
        for child in node.children:
            if len(child.children) == 2:
                term, content = child.children[:2]
                parsed_content.append(term.astext())
                parsed_content.append(
                    textwrap.indent(parse_content(content), "   ") + "\n"
                )

        content = "\n".join(parsed_content).splitlines()
        self.content = StringList(content, content)

        return super().run()


def setup(app: Sphinx):
    app.add_directive("glossarygen", GlossaryGen)
