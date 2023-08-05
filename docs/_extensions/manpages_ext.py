from docutils import nodes
from sphinx.application import Sphinx
from sphinx.builders import manpage as _manbuilder
from sphinx.writers import manpage as _manwriter


class BetterManPageTranslator(_manwriter.ManualPageTranslator):
    _seealso_refs: list[nodes.Element] = []

    def _append_seealso(self):
        for ref in self._seealso_refs:
            try:
                self.body.append(self.visit_reference(ref))
            except nodes.SkipNode:
                pass
            self.body.append(", ")
        self.body.pop()
        self.body.append("\n")

    def visit_reference(self, node: nodes.Element) -> None:
        refuri = node.get("refuri", "")
        if refuri and "#" not in refuri:
            self.body.append(refuri)
            raise nodes.SkipNode
        return super().visit_reference(node)

    def visit_seealso(self, node: nodes.Element):
        self._seealso_refs.append(node)
        raise nodes.SkipNode

    def visit_title(self, node: nodes.Element):
        try:
            super().visit_title(node)
        except nodes.SkipNode as e:
            raise e
        finally:
            if (
                self.deunicode(node.astext().upper()) == "SEE ALSO"
                and self._seealso_refs
            ):
                self._append_seealso()
                self._seealso_refs.clear()

    def depart_document(self, node: nodes.Element):
        if self._seealso_refs:
            self.body.append(".SH SEE ALSO\n.nh\n.sp\n")
            self._append_seealso()
            self._seealso_refs.clear()
        super().depart_document(node)


class ManBuilder(_manbuilder.ManualPageBuilder):
    def get_target_uri(self, docname: str, typ=None) -> str:
        for page in self.config.man_pages:
            if docname == page[0]:
                return f"{page[1]}({page[4]})"
        return super().get_target_uri(docname, typ)


def setup(app: Sphinx):
    app.set_translator("man", BetterManPageTranslator, override=True)
    app.add_builder(ManBuilder, override=True)
