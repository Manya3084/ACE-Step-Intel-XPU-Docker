#!/usr/bin/env python3
"""Mobile sidebar: default closed, full off-canvas when closed, hamburger menu."""
from pathlib import Path
import re

# ---------------------------------------------------------------------------
# Sidebar.tsx — off-canvas on mobile when closed
# ---------------------------------------------------------------------------
sp = Path("components/Sidebar.tsx")
if not sp.exists():
    raise SystemExit("components/Sidebar.tsx not found")

st = sp.read_text()

old_cls = None
# Match the sidebar outer className template (flexible whitespace)
pat_cls = re.compile(
    r"className=\{`\s*"
    r"flex flex-col h-full bg-white dark:bg-suno-sidebar[^`]*?"
    r"\$\{isOpen \? 'w-\[200px\]' : 'w-\[72px\]'\}\s*`\}",
    re.S,
)
m = pat_cls.search(st)
if not m:
    # fallback: replace the isOpen width ternary only + inject mobile classes
    if "-translate-x-full" in st and "md:relative" in st:
        print("Sidebar already looks patched")
    else:
        st2 = st.replace(
            "fixed left-0 top-0 z-50 md:relative",
            "fixed left-0 top-0 z-50 h-screen md:h-full md:relative",
        )
        st2 = st2.replace(
            "${isOpen ? 'w-[200px]' : 'w-[72px]'}",
            "${isOpen ? 'w-[200px] translate-x-0' : 'w-[200px] -translate-x-full md:translate-x-0 md:w-[72px]'}",
        )
        if st2 == st:
            raise SystemExit("Could not patch Sidebar.tsx className")
        st = st2
        print("Sidebar className patched (fallback)")
else:
    new_cls = """className={`
      flex flex-col h-screen md:h-full bg-white dark:bg-suno-sidebar border-r border-zinc-200 dark:border-white/5 flex-shrink-0 py-4 overflow-y-auto scrollbar-hide transition-all duration-300
      fixed left-0 top-0 z-50 md:relative
      ${isOpen
        ? 'w-[200px] translate-x-0'
        : 'w-[200px] -translate-x-full md:translate-x-0 md:w-[72px]'}
    `}"""
    st = pat_cls.sub(new_cls, st, count=1)
    print("Sidebar className patched")

sp.write_text(st)

# ---------------------------------------------------------------------------
# App.tsx — default closed on mobile + hamburger
# ---------------------------------------------------------------------------
ap = Path("App.tsx")
if not ap.exists():
    raise SystemExit("App.tsx not found")
at = ap.read_text()

# 1) Default showLeftSidebar from viewport width
if "window.innerWidth >= 768" not in at and "useState(() =>" not in at.split("showLeftSidebar")[0][-200:]:
    at = at.replace(
        "const [showLeftSidebar, setShowLeftSidebar] = useState(true);",
        """const [showLeftSidebar, setShowLeftSidebar] = useState(() => {
  if (typeof window === 'undefined') return true;
  return window.innerWidth >= 768;
});""",
    )
    print("Default showLeftSidebar from viewport")
else:
    print("showLeftSidebar init already customized")

# 2) Close when switching to mobile
if "setShowLeftSidebar(false)" in at and "isMobile) setShowLeftSidebar" in at:
    # already closes on navigate; add resize effect if missing
    pass
if "/* mobile-sidebar-default-closed */" not in at:
    # inject effect after showLeftSidebar state block
    needle = "const [mobileShowList, setMobileShowList] = useState(false);"
    effect = """const [mobileShowList, setMobileShowList] = useState(false);

  // mobile-sidebar-default-closed: keep nav off-canvas on small screens
  useEffect(() => {
    if (isMobile) setShowLeftSidebar(false);
  }, [isMobile]);"""
    if needle in at:
        at = at.replace(needle, effect, 1)
        print("Added isMobile -> close sidebar effect")
    else:
        print("WARN: mobileShowList needle not found; skip effect")

# Ensure useEffect is imported
if "useEffect" not in at.split("from 'react'")[0] and "from 'react'" in at:
    at = re.sub(
        r"import React, \{([^}]+)\} from 'react'",
        lambda m: (
            m.group(0)
            if "useEffect" in m.group(1)
            else f"import React, {{{m.group(1).strip()}, useEffect}} from 'react'"
        ),
        at,
        count=1,
    )
    # also handle: import { useState, ... } from 'react'
    at = re.sub(
        r"import \{([^}]+)\} from 'react'",
        lambda m: m.group(0) if "useEffect" in m.group(1) else f"import {{{m.group(1).strip()}, useEffect}} from 'react'",
        at,
        count=1,
    )
    print("Ensured useEffect import")

# 3) Floating hamburger when mobile + sidebar closed
if "ace-mobile-nav-btn" not in at:
    # Place just before Sidebar component
    hamburger = """
      {/* ace-mobile-nav-btn: open off-canvas left nav on mobile */}
      {isMobile && !showLeftSidebar && (
        <button
          type="button"
          id="ace-mobile-nav-btn"
          aria-label="Open menu"
          onClick={() => setShowLeftSidebar(true)}
          className="fixed top-3 left-3 z-[55] md:hidden flex items-center justify-center w-11 h-11 rounded-full bg-zinc-900/90 text-white border border-white/15 shadow-lg backdrop-blur-sm active:scale-95"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
      )}
"""
    if "<Sidebar" in at:
        at = at.replace("<Sidebar", hamburger + "\n      <Sidebar", 1)
        print("Injected mobile hamburger before Sidebar")
    else:
        print("WARN: <Sidebar not found")
else:
    print("Hamburger already present")

ap.write_text(at)
print("mobile-sidebar patch complete")
