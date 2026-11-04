---
id: APP-008
skill: app-analysis
category: service and brand
classification: observed
confidence: high
source: krita-ai-diffusion ai_diffusion/backend/cloud_client.py:82-83,148-149; model/updates.py:37,73-75
conflicts_with: []
---

The "Online Service" connection mode, the plugin auto-update and news all go through Interstice (`api.interstice.cloud`), the plugin author's commercial service. It uses browser device-flow sign-in and a token stored in `settings.json`. A third-party port cannot reuse it without an agreement.
