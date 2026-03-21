# AGENTS.md

## Purpose
This file instructs the LLM coding assistant on how to safely, consistently, and correctly contribute to this project.  
It defines rules, workflows, and expectations that must be followed for all generated code and changes.

---

## Project Authority
- Always treat `PLAN.md` as the authoritative source of truth.
- All decisions must align with the goals, scope, and priorities defined in `PLAN.md`.
- Do not introduce features, changes, or refactors that are not aligned with the plan.
- If something is unclear, refer back to `PLAN.md` before proceeding.
- If ambiguity remains, ask for clarification before making changes.

---

## Git Commit Strategy
- Commit after each logical unit of work is completed.
- Each commit must represent a coherent, atomic change.
- Use semantic commit messages:
  - `feat`: new features
  - `fix`: bug fixes
  - `docs`: documentation updates
  - `refactor`: code restructuring without behavior change
  - `test`: adding or updating tests
  - `chore`: maintenance tasks
- Never commit:
  - Partial implementations
  - Broken or non-functional code
  - Experimental or debug-only changes
- Ensure the codebase is always in a working state after each commit.

---

## Environment Constraints
- All code must be executed and tested inside the provided devcontainer.
- Do not install or modify packages on the host machine.
- Do not rely on host-specific dependencies or configurations.
- Ensure all dependencies are explicitly defined and reproducible within the container.
- Treat the container environment as the single source of truth for runtime behavior.

---

## Documentation Maintenance
- Keep all documentation accurate and up to date with the codebase.

### README.md
- If `README.md` does not exist:
  - Create it.
  - Include:
    - High-level project description
    - Setup instructions
    - Basic usage examples
- Continuously update it whenever the codebase changes.
- Ensure it remains accessible to a nominally technical user.

### IMPLEMENTATION.md
- If `IMPLEMENTATION.md` does not exist:
  - Create it.
- Continuously update it whenever the codebase changes.
- Include:
  - System architecture overview
  - Key components and their responsibilities
  - Data flows and interactions
  - Important design decisions
- This file serves as context for future planning and LLM-assisted development.

---

## Interaction Tips
- Always review `PLAN.md` before writing or modifying code.
- Prioritise tasks based on the order and structure defined in `PLAN.md`.
- Ask for clarification when:
  - Requirements are ambiguous
  - Multiple valid approaches exist
  - A task conflicts with the current plan
- Break down complex tasks into smaller, manageable steps.
- Prefer incremental progress over large, risky changes.
- Ensure each step aligns with the overall plan before proceeding.
