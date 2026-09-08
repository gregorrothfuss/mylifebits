# Agent Execution Contract (Python / Antigravity)

## 1. State Management & Context Hygiene (Strict JSON Protocol)

### Anti-Pollution & Log Offloading
- **Never stream raw execution logs > 25 lines into context.**
- Redirect all verbose output (tests, linters, server logs) directly to scratch files:
  `uv run pytest > .agent/scratch/pytest.log 2>&1`
- Read only the relevant failure slice using targeted extraction (`tail -n 25 .agent/scratch/pytest.log` or file inspection tools).
- Keep conversation turns strictly bounded to decisions, diffs, and exact error signatures.

### Mandatory State Tracking (`.agent/state.json`)
All multi-step tasks MUST maintain their active execution graph inside `.agent/state.json` adhering strictly to this schema:

```json
{
  "goal": "<One-sentence objective>",
  "active_step_id": 1,
  "steps": [
    {
      "id": 1,
      "description": "<Atomic action being executed>",
      "status": "in_progress"
    },
    {
      "id": 2,
      "description": "<Subsequent or refactor step verification>",
      "status": "pending"
    }
  ],
  "context_cache": {
    "target_files": ["src/module.py"],
    "test_files": ["tests/test_module.py"],
    "scratch_logs": [".agent/scratch/pytest.log"]
  }
}
```

### State Machine Enforcement Rules
1. **Pre-Execution Check:** Inspect `.agent/state.json` at the start of every turn before invoking any other tool.
2. **Atomic Transition:** Update `active_step_id` and mark the step `"status": "in_progress"` *before* modifying code or running heavy processes.
3. **Completion Verification:** Mark a step `"status": "completed"` ONLY after verifying changes with a clean linter/test exit code (`0`).
4. **Failure State:** If a step fails unexpectedly, set `"status": "failed"`, record the log path in `context_cache`, and do not proceed to dependent steps until resolved.

---

## 2. Local Version Control & Commit Protocol (Archaeology Standard)

### Commit Cadence & Atomic Changes
- **Commit on Every Verified Step:** Whenever a step in `.agent/state.json` transitions to `"completed"`, immediately stage the modified files and commit. Never batch multiple unrelated changes into one commit.
- **Explicit File Staging:** Stage files individually (`git add src/module.py tests/test_module.py`). NEVER run `git add .` or `git add -A`.
- **Clean Tree Invariant:** Before starting any new task or step, run `git status` to ensure a clean working tree.
- **Rollback Discipline:** If an experiment or implementation fails, do not patch over broken code with messy workarounds. Revert cleanly (`git checkout -- <files>` or `git restore <files>`) back to the last verified commit before attempting an alternate solution.

### Commit Message Specification
Commit messages must strictly follow the Conventional Commits format with a structured body designed for human review and future agent archaeology:

```text
<type>(<scope>): <imperative summary under 72 chars>

Why:
- Root cause, architectural intent, or requirement driving this change.
- Specific problem or bug being solved.

What:
- Key structural changes made (classes, functions, data flow).
- Any edge cases or trade-offs intentionally introduced.

Verification:
- Command: `uv run pytest tests/path/test_file.py -k "test_name"` (Exit 0)
- Command: `uv run ruff check && uv run mypy .` (Exit 0)

State-Step: <step_id from state.json>
```

**Allowed Types:**
- `feat`: New user-facing or system capability.
- `fix`: Bug fix, error resolution, or regression patch.
- `refactor`: Structural code change without behavior alteration.
- `test`: Adding or modifying test fixtures, mocks, or assertions.
- `chore`: Tooling, dependency updates, or configuration adjustments.

---

## 3. Runtime Environment & Toolchain
- **Environment Manager:** Use `uv` strictly. Never run bare `pip` or modify global interpreters.
  - Install dependencies: `uv sync`
  - Add dependency: `uv add <package>` (or `uv add --dev <package>`)
  - Run scripts: `uv run python <script.py>`
  - Run tests: `uv run pytest -v`
  - Run focused test: `uv run pytest -k "<test_name>" -s`
  - Linting & Formatting: `uv run ruff check --fix && uv run ruff format`
  - Static Type Analysis: `uv run mypy .`

---

## 4. Process Persistence & Long-Running Tasks
- **No Ephemeral Background Subshells:** Do not launch detached jobs using raw `&` or standalone `caffeinate`.
- **Persistent Workers:** For tasks running >30s (servers, watch modes, batch jobs), launch via `tmux` with a display/system sleep assertion:
  `tmux new-session -d -s worker "caffeinate -dims uv run python <entrypoint>"`
- **Verification:** Monitor status via `kill -0 <pid>` or `tmux capture-pane -pt worker`. Verify logs and exit codes on disk rather than assuming success.

---

## 5. Execution Boundaries & Anti-Laziness Directives

### Directives:
- **Zero Omission Policy:** NEVER output `# ... existing code ...`, `# TODO: implement`, or truncated placeholder blocks. Write complete, functional diffs or deterministic patches.
- **Read Before Write:** Inspect file contents, imports, and type signatures before patching. Never guess paths or interfaces.
- **Closed-Loop Verification:** Complete fixes must follow: *Inspect/Reproduce -> Minimal Fix -> Verify (`ruff` + `pytest`) -> Update `state.json` -> Atomic Git Commit*.

### ALWAYS:
- Include Python 3.10+ type annotations on all public functions.
- Prefer `pathlib.Path` over `os.path`.
- Handle exceptions explicitly; avoid bare `except:` statements.
- Clean up any spawned child processes or test artifacts before ending a task.

### NEVER:
- Commit secrets, credential files, `.env`, or `.agent/scratch/` contents.
- Modify files in `.venv/`, lockfiles manually, or cache directories (`__pycache__/`, `.pytest_cache/`).
- Commit unverified code with failing tests or lint errors.

---

## 6. Learned Invariants & Forbidden Patterns

### Explicit Negative Constraints (Derived from Git Failure Archaeology)

1. **Ground Truth Baseline Purity**:
   - **NEVER** query the modified master database (e.g., `timeline_viewer.db`) or inject synthetic cards/badges to render baseline ground truth; **always** read directly and unmodified from authentic baseline sources (`pixel10_export/Timeline-latest.json` or `scratch/original_gms_backup/.../odlh-storage.db`) to ensure 100% ground-truth baseline fidelity.

2. **Strict Dual-Source Asset Isolation**:
   - **NEVER** share, copy, or cross-paste screenshot crops, map viewports, polylines, or database cursors between baseline and master comparison panels; **always** isolate source assets completely so that the baseline panel renders strictly baseline artifacts and the master panel renders strictly master artifacts.

3. **Zero Presentation-Layer Card Fabrication**:
   - **NEVER** hardcode fake POI visits, synthetic gap cards, or candidate missing visit badges (e.g., `Ave A & 6th St`, `Prod Gap: 114 min`) in presentation scripts to explain unrecorded telemetry intervals; **always** preserve raw intervals faithfully as authentic unrecorded gaps or native moving segments.

4. **Multi-Factor Physical Validation for Travel Modes**:
   - **NEVER** assign or impute `FLYING` based solely on coarse distance thresholds (e.g., `dist > 50km`); **always** verify physical flight constraints first: distance $>300\text{ km}$, average speed $>250\text{ km/h}$, and spatial proximity ($<5\text{ km}$) to verified airport POIs. Ground transitions below $300\text{ km}$ must default to `IN_PASSENGER_VEHICLE`.

5. **Continuous Overnight Visit Integrity**:
   - **NEVER** split, duplicate, or truncate an overnight visit at midnight (00:00 local or UTC) into artificial "Left at 12:00 AM" / "Arrived at 12:00 AM" segments; **always** verify that overnight stays spanning across midnight remain a single contiguous visit entity across day transitions.

6. **Binary Protobuf & Feature ID Preservation**:
   - **NEVER** slice or arbitrarily offset binary Place ID or Feature ID strings (e.g., `place_id[4:]`) before decoding; **always** verify the exact 20-byte protobuf byte alignment against Google Maps cell ID and fingerprint specifications before applying transformations.

7. **Map Viewport and List Alignment**:
   - **NEVER** pair an unedited raw baseline map crop (containing raw path polylines or `~` moving markers) with a cleaned semantic card list; **always** verify that the map visual layer strictly corresponds to the underlying database entities shown in the card list below.