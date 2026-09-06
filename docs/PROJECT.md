# Project: TOONFLOW AI

## Project identity

TOONFLOW AI is a Blender AI Automation Extension / Add-on. Its tagline is: **Turn Scripts into 3D Cartoon Videos — Directly Inside Blender.**

## Product goal

Enable creators to move from a text concept or script toward an automated 3D cartoon production workflow within Blender.

## Problem being solved

Creating animated 3D cartoon scenes requires many connected planning and Blender operations. TOONFLOW AI aims to reduce repetitive setup by turning an approved, structured scene plan into controlled Blender actions.

## Target users

- Independent 3D cartoon creators and animators
- Small creative studios
- Storytellers and educators working with Blender-based animation
- Creators who need a guided bridge from written ideas to a 3D scene

## Core philosophy

**AI plans. Blender executes.**

AI produces structured scene-planning data. The add-on validates that data and invokes only controlled Blender automation. AI-generated arbitrary Python code must never be executed directly in Blender.

## MVP goal

The first MVP is intended to support this controlled path:

```text
User concept or script
→ AI scene analysis
→ Structured JSON scene plan
→ Blender add-on automation
→ Predefined asset loading and placement
→ Predefined basic animation assignment
→ Basic camera configuration
→ 3D cartoon scene
```

## MVP limitations

The current phase establishes only the Blender add-on skeleton: package metadata and registration entry points. It must not implement UI, bpy automation, Blender operators, Ollama integration, dependencies, AI providers, schemas, or product features.

The broader MVP also excludes cloud AI, MCP, SaaS services, authentication, payments, voice, lip sync, rendering automation, AI-generated models or animations, a node editor, and a web app.

## Long-term vision

TOONFLOW AI may eventually guide a production flow from a concept or script through scene breakdown, character and environment detection, emotion and action planning, Blender automation, voice and lip sync, rendering, and final video. These capabilities are future roadmap items and are not implied by the current foundation.
