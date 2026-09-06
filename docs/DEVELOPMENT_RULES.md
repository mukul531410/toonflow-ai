# Development Rules

These rules apply to all contributors and AI coding agents. Read the relevant project documentation before starting work.

1. Always read relevant project documentation before starting work.
2. Never assume architecture without checking the documentation.
3. Do not introduce dependencies without explicit approval.
4. Do not modify unrelated files.
5. Keep tasks focused and scoped.
6. Keep Blender-specific logic separate from AI provider logic.
7. AI providers must remain replaceable.
8. Ollama is the initial AI provider.
9. AI output must use structured data.
10. Validate AI output before execution.
11. Never directly execute arbitrary AI-generated Python code inside Blender.
12. Blender operations must use controlled operators and services.
13. Keep modules small and focused.
14. Do not implement future roadmap features early.
15. Follow the current MVP scope.
16. Avoid unnecessary abstractions.
17. Prefer clear and maintainable code over clever code.
18. Never delete or overwrite unrelated work.
19. Report files changed after every implementation task.
20. Report testing performed and known limitations.
21. Stop when the requested task is complete.
22. Ask for clarification when a requirement conflicts with project documentation.
