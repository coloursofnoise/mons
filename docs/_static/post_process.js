// Some hard-coded post processing to tweak generated documentation.
$(function() {
    const srcOpt = $("#cmdoption-mons-install-src .descclassname");
    srcOpt.contents().first()[0].textContent="[=";
    srcOpt.append("]");
})
