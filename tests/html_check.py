"""HTML structure check shared by the tests: every opened element must be closed, in order.

Added 2026-11-09 after a stray </div> pushed the Lake Detail observation log out of the page layout. The
bug was found by eye on a screenshot; conftest.py now runs this check on EVERY HTML response any test gets.
"""
from html.parser import HTMLParser

VOID = {"img", "br", "input", "link", "meta", "hr", "line", "rect", "circle", "polygon", "polyline", "path"}


def unbalanced_tags(html: str) -> list:
    """[] if balanced; otherwise (closing tag, line, element actually open) for each mismatch, plus unclosed tags."""
    class Check(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.problems = [], []

        def handle_starttag(self, tag, attrs):
            if tag not in VOID:
                self.stack.append(tag)

        def handle_endtag(self, tag):
            if tag in VOID:
                return
            if self.stack and self.stack[-1] == tag:
                self.stack.pop()
            else:
                self.problems.append((tag, self.getpos()[0], self.stack[-1] if self.stack else None))

    c = Check()
    c.feed(html)
    return c.problems + [("unclosed", t) for t in c.stack]
