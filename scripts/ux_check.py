"""UX + accessibility audit of the React UI (static, no browser needed).

Complements `src/test/a11y.test.jsx` (axe-core on rendered screens) with the
checks axe cannot do in jsdom or cannot do at all:

  * WCAG contrast maths on the real design tokens and component colour pairs
  * design-system discipline (palette size, radii, shadows, type scale)
  * class coverage: every class the components use is actually styled
  * keyboard affordances (focus rings, hit-target sizes)
  * UX states: loading / empty / error / destructive-confirmation per page

    cd frontend && python3 ../scripts/ux_check.py

Exit code is non-zero when a check fails.
"""

import os
import re
import sys

FRONTEND = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "frontend"))
SRC = os.path.join(FRONTEND, "src")
CSS_PATH = os.path.join(SRC, "index.css")

PASSED = 0
FAILED = 0
FAILURES = []


def check(label, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS  {label}")
    else:
        FAILED += 1
        FAILURES.append(label)
        print(f"  FAIL  {label}  {detail}")


# ---------------------------------------------------------------------------
# Colour maths
# ---------------------------------------------------------------------------
def parse_hex(value):
    value = value.strip()
    if not value.startswith("#"):
        return None
    value = value[1:]
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return None
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def luminance(rgb):
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg, bg):
    l1, l2 = luminance(fg), luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


css = open(CSS_PATH, encoding="utf-8").read()

# --- Design tokens ---------------------------------------------------------
root_block = re.search(r":root\s*\{(.*?)\}", css, re.S).group(1)
tokens = dict(re.findall(r"--([\w-]+):\s*([^;]+);", root_block))

print("\n[A] Minimal design system")
check("a single :root token block defines the system", len(tokens) >= 20, f"{len(tokens)} tokens")

colour_tokens = {k: v for k, v in tokens.items() if parse_hex(v)}
check(
    "palette is a small set of role tokens",
    6 <= len(colour_tokens) <= 28,
    f"{len(colour_tokens)} colours: {sorted(colour_tokens)}",
)
# Every token must be used: an unused token is a colour nobody can see.
token_body = css[css.index("}", css.index(":root")) :]
unused_tokens = [name for name in tokens if f"var(--{name})" not in token_body and name != "font"]
check("no unused tokens", not unused_tokens, str(unused_tokens))

# Hex values used outside :root would be ad-hoc palette additions. Gradients and
# rgba() overlays are not counted; a couple of text-on-soft-background shades are
# allowed but must stay rare.
outside = css[css.index("}", css.index(":root")) :]
ad_hoc = sorted(set(re.findall(r"#[0-9a-fA-F]{3,6}\b", outside)))
check("no ad-hoc colours outside the token block", not ad_hoc, f"{len(ad_hoc)}: {ad_hoc}")

radii = sorted(set(re.findall(r"border-radius:\s*([^;]+);", css)))
check("border radii come from the scale", len(radii) <= 5, str(radii))

shadows = re.findall(r"box-shadow:\s*([^;]+);", css)
check("shadows are reserved for overlays (<= 2 declarations)", len(shadows) <= 2, str(shadows))

type_tokens = {k: v for k, v in tokens.items() if k.startswith("text-")}
literal_sizes = [
    size for size in re.findall(r"font-size:\s*([^;]+);", css) if "var(" not in size
]
check("every font size comes from the scale", not literal_sizes, str(literal_sizes[:4]))
check(f"type scale has <= 8 steps ({len(type_tokens)})", len(type_tokens) <= 8, str(sorted(type_tokens)))

# Only three properties are allowed to be forced: motion cannot be disabled any
# other way, and print must drop chrome that overlaps the page.
allowed_important = {"transition-duration", "animation-duration", "display"}
forced = [
    match.group(1)
    for match in re.finditer(r"^\s*([\w-]+)\s*:[^;]*!important", css, re.M)
]
check(
    "!important is limited to reduced-motion and print rules",
    set(forced) <= allowed_important,
    str(sorted(set(forced) - allowed_important)),
)

# --- Class coverage --------------------------------------------------------
used = set()
for root, _dirs, files in os.walk(SRC):
    for name in files:
        if not name.endswith(".jsx"):
            continue
        text = open(os.path.join(root, name), encoding="utf-8").read()
        for literal in re.findall(r'className="([^"]+)"', text):
            used.update(literal.split())
        for literal in re.findall(r"className=\{`([^`]+)`\}", text):
            cleaned = re.sub(r"\$\{[^}]*\}", " ", literal)
            used.update(cleaned.split())
        for expr in re.findall(r"className=\{[^}]*\}", text):
            for lit in re.findall(r"'([^']+)'", expr):
                used.update(lit.split())

styled = set(re.findall(r"\.([a-zA-Z][\w-]*)", css))
unstyled = sorted(used - styled)
check(f"every class used by the components is styled ({len(used)} classes)", not unstyled, str(unstyled))

# Responsive overrides legitimately repeat selectors inside @media blocks and a
# selector may be split into two blocks for readability - what must never happen
# is the same selector setting the same property twice (order-dependent CSS).
top_level = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
blocks = {}
for selector, body in re.findall(r"^\s*([.#][^{@\n]+)\{([^}]*)\}", top_level, re.M):
    props = {
        prop.strip()
        for prop in re.findall(r"([\w-]+)\s*:", body)
        if prop.strip() not in {"content", "} "}
    }
    blocks.setdefault(selector.strip(), []).append(props)
conflicts = sorted(
    sel for sel, prop_sets in blocks.items() if len(prop_sets) > 1 and set.intersection(*prop_sets)
)
check("no selector declares the same property twice", not conflicts, str(conflicts[:5]))


print("\n[B] Colour contrast (WCAG AA)")

def token_colour(name):
    value = tokens.get(name, "")
    return parse_hex(value)


PAIRS = [
    ("text", "surface", 4.5, "body text on cards"),
    ("text", "bg", 4.5, "body text on page background"),
    ("muted", "surface", 4.5, "secondary text on cards"),
    ("muted", "surface-muted", 4.5, "secondary text on tinted rows"),
    ("accent", "surface", 4.5, "links and accents on cards"),
    ("accent", "accent-soft", 4.5, "active nav item"),
    ("danger", "surface", 4.5, "error text"),
    ("success", "surface", 4.5, "success text"),
    ("success", "success-soft", 4.5, "success alert"),
    ("danger", "danger-soft", 4.5, "error alert"),
    ("border-strong", "surface", 3.0, "input borders (non-text UI)"),
]

for fg, bg, minimum, label in PAIRS:
    fg_rgb, bg_rgb = token_colour(fg), token_colour(bg)
    if not fg_rgb or not bg_rgb:
        check(f"contrast {label}", False, f"missing token {fg}/{bg}")
        continue
    ratio = contrast(fg_rgb, bg_rgb)
    check(f"contrast {label}: {ratio:.2f}:1 (min {minimum})", ratio >= minimum, f"{ratio:.2f}")

white = (255, 255, 255)
for token_name, label in (("accent", "primary button label"), ("danger", "danger button label")):
    ratio = contrast(white, token_colour(token_name))
    check(f"white on {label}: {ratio:.2f}:1", ratio >= 4.5, f"{ratio:.2f}")

# Text on tinted backgrounds that are written as literals in component rules.
for literal, bg_literal, label, minimum in (
    ("#7a271a", "#fef3f2", "error alert text on tint", 4.5),
    ("#085d3a", "#ecfdf3", "success alert text on tint", 4.5),
    ("#4b5563", "#f3f4f6", "uppercase table header", 4.5),
):
    ratio = contrast(parse_hex(literal), parse_hex(bg_literal))
    check(f"contrast {label}: {ratio:.2f}:1 (min {minimum})", ratio >= minimum, f"{ratio:.2f}")


print("\n[C] Keyboard & touch")
check("a global :focus-visible ring is defined", ":focus-visible" in css and "outline:" in css)
check("focus ring is not suppressed", "outline: none" not in css and "outline:none" not in css)

def rule_block(selector):
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    return match.group(1) if match else ""

def min_height(selector):
    body = rule_block(selector)
    match = re.search(r"min-height:\s*(\d+)px", body)
    return int(match.group(1)) if match else None

btn_height = min_height(".btn")
check("buttons are at least 40px tall", btn_height is not None and btn_height >= 40, str(btn_height))
option_height = min_height(".option")
check("answer options are at least 44px tall", option_height is not None and option_height >= 44, str(option_height))
check("coarse-pointer media query enlarges buttons", "pointer: coarse" in css)
check("prefers-reduced-motion is honoured", "prefers-reduced-motion" in css)


print("\n[D] Component semantics")
pages = {}
for root, _dirs, files in os.walk(os.path.join(SRC, "pages")):
    for name in files:
        if name.endswith(".jsx"):
            pages[name] = open(os.path.join(root, name), encoding="utf-8").read()

jsx_all = {name: open(os.path.join(root, name), encoding="utf-8").read()
           for root, _dirs, files in os.walk(SRC) for name in files if name.endswith(".jsx")}

modal = jsx_all.get("Modal.jsx", "")
check("modal exposes role=dialog + aria-modal", 'role="dialog"' in modal and 'aria-modal="true"' in modal)
check("modal is labelled by its title", "aria-labelledby" in modal)
check("modal traps Tab", "event.key !== 'Tab'" in modal)
check("modal restores focus on close", "opener.focus" in modal or "openerRef" in modal)
check("modal closes on Escape", "'Escape'" in modal)

timer_pages = [name for name, text in pages.items() if "timer" in text and "exam" in name.lower()]
check("the exam timer announces updates (aria-live)", timer_pages and 'aria-live' in pages[timer_pages[0]])

check("no native alert()/confirm() dialogs", not re.search(r"\b(window\.)?(alert|confirm)\(", "".join(jsx_all.values())))
check("no dangerouslySetInnerHTML", not any("dangerouslySetInnerHTML" in t for t in jsx_all.values()))
clickable_without_role = []
for name, text in jsx_all.items():
    for tag in re.findall(r"<(?:div|span)\b[^>]*onClick[^>]*>", text, re.S):
        if "role=" not in tag and "tabIndex" not in tag:
            clickable_without_role.append(name)
check("clickable divs/spans carry a role (or are pointer-only shortcuts)", not clickable_without_role, str(sorted(set(clickable_without_role))))

fields = re.findall(r"<Field\b([^>]*)>", "".join(jsx_all.values()))
missing_ids = [f for f in fields if "id=" not in f]
check(f"all {len(fields)} Field inputs are label-linked", not missing_ids, str(len(missing_ids)))

html = open(os.path.join(FRONTEND, "index.html"), encoding="utf-8").read()
check("document declares its language", 'lang="en"' in html)
check("document has a meaningful title", "<title>" in html and "Auspify" in html)


print("\n[E] UX states per page")
fetching = {name: text for name, text in pages.items() if "await " in text and "Api." in text}
check(f"{len(fetching)} pages fetch data", len(fetching) >= 8, str(sorted(fetching)))

for label, needle in (("loading state", "Spinner"), ("error feedback", "Alert")):
    missing = [name for name, text in fetching.items() if needle not in text]
    check(f"every fetching page has a {label}", not missing, str(missing))

empty_states = [name for name, text in pages.items() if re.search(r"No [a-z].*\.|not [a-z]+ yet|will appear", text)]
check("list pages define empty states", len(empty_states) >= 3, str(sorted(empty_states)))

check("destructive actions ask for confirmation", "Delete this exam?" in jsx_all.get("TeacherExamsPage.jsx", ""))
check("exam submission asks for confirmation", "Submit your exam?" in jsx_all.get("TakeExamPage.jsx", ""))
check("forms show inline field errors", "field-error" in css and "aria-invalid" in jsx_all.get("ui.jsx", ""))
check("the countdown is derived from the server value", "remaining_seconds" in pages.get("TakeExamPage.jsx", ""))
check("leaving an open attempt warns", "beforeunload" in pages.get("TakeExamPage.jsx", ""))
check("a 404 screen exists", "404" in jsx_all.get("App.jsx", ""))
check("a 403 screen exists", "403" in jsx_all.get("ProtectedRoute.jsx", ""))

print("\n" + "=" * 60)
print(f"UX checks: {PASSED} passed, {FAILED} failed")
if FAILURES:
    print("Failures:")
    for failure in FAILURES:
        print(f"  - {failure}")
print("=" * 60)
sys.exit(1 if FAILED else 0)
