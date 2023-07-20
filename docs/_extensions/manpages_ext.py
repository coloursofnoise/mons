from docutils import nodes
from sphinx.application import Sphinx
from sphinx.builders import manpage as _manbuilder
from sphinx.writers import manpage as _manwriter


class BetterManPageTranslator(_manwriter.ManualPageTranslator):
    def visit_reference(self, node: nodes.Element) -> None:
        refuri = node.get("refuri", "")
        if refuri and "#" not in refuri:
            self.body.append(refuri)
            raise nodes.SkipNode
        return super().visit_reference(node)


class ManBuilder(_manbuilder.ManualPageBuilder):
    def get_target_uri(self, docname: str, typ=None) -> str:
        for page in self.config.man_pages:
            if docname == page[0]:
                return f"{page[1]}({page[4]})"
        return super().get_target_uri(docname, typ)


def setup(app: Sphinx):
    app.set_translator("man", BetterManPageTranslator, override=True)
    app.add_builder(ManBuilder, override=True)
