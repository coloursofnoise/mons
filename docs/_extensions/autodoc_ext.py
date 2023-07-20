import copy

from docutils.parsers.rst import directives
from sphinx.application import Sphinx
from sphinx.domains.python import PyAttribute
from sphinx.ext import autodoc


class ClassMembersDocumenter(autodoc.ClassDocumenter):
    option_spec = {
        **autodoc.ClassDocumenter.option_spec,
        "skip_docstr": directives.unchanged,
    }
    objtype = "classmembers"

    def generate(self, *args, **kwargs) -> None:
        self.options["members"] = autodoc.ALL
        self.is_toplevel = not self.options.get("classmembersdocumenter", False)
        self.options["classmembersdocumenter"] = True
        self.doc_as_attr = False

        super().generate(*args, **kwargs)

        if not self.is_toplevel:
            return

        result_strlist = self.directive.result

        result_strlist.trim_start(4)
        result_strlist.trim_left(3)

        s_drop = list()
        current_prefix = ""
        for i in range(len(result_strlist)):
            s: str = result_strlist[i]

            if ".. py:classmembers::" in s:
                current_prefix = s.split()[-1] + "."

            if ":value:" in s:
                s_drop.append(s)
                continue

            if ":type:" in s and "~typing.Optional" in s:
                result_strlist[i] = s.replace("~typing.Optional[", "")[:-1]

            if ".. py:classmembersattribute::" in s:
                directive, arguments = s.rstrip().split("::", maxsplit=1)
                result_strlist[i] = (
                    directive + ":: " + current_prefix + arguments.split(".")[-1]
                )

        for s in s_drop:
            result_strlist.remove(s)

    def document_members(self, all_members: bool = False):
        objpath = self.objpath
        if not self.object.__init__.__qualname__.startswith(self.object.__qualname__):
            self.objpath = self.object.__init__.__qualname__.split(".")[:-1]

        super().document_members(all_members)

        self.objpath = objpath

    def add_content(self, more_content) -> None:
        skip_docstr = self.options.get("skip_docstr", None)
        if skip_docstr and not (skip_docstr == "all" or self.is_toplevel):
            super().add_content(more_content)

    def get_object_members(self, want_all: bool) -> tuple[bool, autodoc.ObjectMembers]:
        t_del = list()
        for n, m in self.object.__dict__.items():
            t = type(m)
            if getattr(self.object, t.__name__, None) == t:
                t_del.append(t.__name__)
                t = copy.copy(t)
                t.__qualname__ = t.__qualname__.replace(t.__name__, n)
                t.__name__ = n
                setattr(self.object, n, t)

        ret, members = super().get_object_members(want_all)

        members = [(n, m) for n, m in members if n not in t_del]
        return ret, members

    def format_signature(self, **kwargs) -> str:
        return ""


class ClassMembersAttributeDocumenter(autodoc.AttributeDocumenter):
    objtype = "classmembersattribute"

    def generate(self, *args, **kwargs) -> None:
        super().generate(*args, **kwargs)

    def import_object(self, raiseerror: bool = False) -> bool:
        ret = super().import_object(raiseerror)
        self.parent.__qualname__ = ".".join(self.objpath[:-1])
        return ret


class PyClassMember(PyAttribute):
    def get_signatures(self):
        return [sig.split(".")[-1] for sig in super().get_signatures()]


class ClassMembersDirective(PyClassMember):
    option_spec = {**PyAttribute.option_spec, "toplevel": directives.unchanged}
    allow_nesting = True


class AutoDocstr(
    autodoc.ClassLevelDocumenter,
    autodoc.ModuleLevelDocumenter,
    autodoc.ModuleDocumenter,
):
    objtype = "docstr"
    content_indent = ""

    @classmethod
    def can_document_member(cls, *args, **kwargs):
        return False

    def add_line(self, *args, **kwargs) -> None:
        self.indent = ""
        return super().add_line(*args, **kwargs)

    def resolve_name(self, *args, **kwargs):
        module, name = autodoc.ClassLevelDocumenter.resolve_name(self, *args, **kwargs)

        if not module:
            module, name = autodoc.ModuleLevelDocumenter.resolve_name(
                self, *args, **kwargs
            )

        if not module:
            module, name = autodoc.ClassLevelDocumenter.resolve_name(
                self, *args, **kwargs
            )

        return module, name

    def document_members(self, all_members: bool = False) -> None:
        pass  # skip

    def add_directive_header(self, sig: str) -> None:
        pass  # skip


def setup(app: Sphinx):
    app.add_autodocumenter(AutoDocstr)
    app.add_autodocumenter(ClassMembersDocumenter)
    app.add_autodocumenter(ClassMembersAttributeDocumenter)
    app.add_directive_to_domain("py", "classmembers", ClassMembersDirective)
    app.add_directive_to_domain("py", "classmembersattribute", PyClassMember)
