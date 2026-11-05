"""Widgets for AI diffusion workflows."""

import krita

# PhotoCraft: animation (the Animation workspace, the Graph workspace's Generate Animation and
# live recording) waits for a PhotoCraft timeline (REQ-26). It stays in the code, behind this
# switch; in Krita it is on.
ANIMATION_ENABLED = not hasattr(krita, "photocraft_host")
