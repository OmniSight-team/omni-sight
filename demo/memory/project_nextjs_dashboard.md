---
name: project-nextjs-dashboard
description: The Phase A demo UI will be a Next.js dashboard, not a CLI tool — no CLI demo code wanted
metadata:
  type: project
---

The demo and user-facing interface for OmniSight Phase A is a Next.js dashboard.

**Why:** User explicitly does not want CLI demos. The Next.js frontend is the intended way to interact with the system.

**How to apply:** Do not build or suggest CLI demo wrappers (argparse scripts, Click apps, etc.) for demoing features. When demo/UI work is needed, default to Next.js components. The service `__main__.py` files should be minimal service entry points (message queue workers), not video-file CLI demos.
