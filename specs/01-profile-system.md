# Profile System Specification

## Overview

Profile is the **single source of truth for agent personality and project context**. It contains:

- **Plugin declarations** — Which extensions the agent uses (plugins provide hooks, commands, MCPs)
- **Rules and conventions** — What the agent should and shouldn't do
- **Project context** — Stack, key files, learned patterns
- **Reporting preferences** — How to show results to user

**Key principle:** Profile is **configuration**, not infrastructure. Plugins handle commands/hooks/MCPs. Bridge generates everything else (CLAUDE.md, settings.json).

Profile evolves over time through enhancement (learning), but user-defined hard rules never change.

---

## 1. Profile Schema

### 1.1 File Location

```
~/.claude-bridge/agents/{agent-name}/profile.yaml
```

**Naming constraints:**
- Alphanumeric + hyphen only
- Must be unique (no two agents with same name)
- Recommended: `{role}-{project-name}` (e.g., `coder-my-app`)

### 1.2 Complete Schema

```yaml
# ══════════════════════════════════════════════════════════════
# METADATA — Auto-managed by Bridge
# ══════════════════════════════════════════════════════════════

name: string                          # Unique agent name
version: integer                      # Incremented on each enhancement (starts at 1)
created: ISO8601 datetime             # When agent created (never changes)
last_enhanced: ISO8601 datetime | null  # When last enhanced (null if never)
base_template: string                 # Template used: coder-fullstack | researcher | reviewer | devops | writer | analyst

# ══════════════════════════════════════════════════════════════
# IDENTITY — User-defined, mostly static
# ══════════════════════════════════════════════════════════════

identity:
  role: string                        # coder | researcher | reviewer | devops | writer | analyst
  display_name: string                # For humans (e.g., "Senior Full-stack Developer")
  project: string                     # Absolute path to project root
  description: string                 # One-line description of what agent does

# ══════════════════════════════════════════════════════════════
# CONTEXT — Learned automatically, enhanced over time
# ══════════════════════════════════════════════════════════════

context:
  stack:
    - string                          # Technology list: [nextjs, typescript, prisma, react-query]

  key_files:                          # Important reference files (docs, configs, schemas)
                                      # NOT code files agent edits (too noisy)
    - path: string                    # Relative path to file/dir
                                      # Examples: prisma/schema.prisma, docs/payment-flow.md, .env.example
      reason: string                  # Why it's important
                                      # Can include signal origin: "Agent asked about this 5 times"
      sensitive: boolean              # Requires confirmation before edit (default: false)
      auto_added: boolean             # Added by Bridge? (vs user-added)
      importance: string              # critical | high | medium (used for CLAUDE.md prioritization)

# ══════════════════════════════════════════════════════════════
# RULES — Hard rules are IMMUTABLE, soft rules evolve via enhancement
# ══════════════════════════════════════════════════════════════

rules:
  hard:                               # User-defined at onboarding, NEVER changed by enhancement
    - text: string                    # "No push to main without PR"
      added_by: string                # user | onboarding
      added_date: ISO8601 datetime

  soft:                               # Learned rules that evolve through enhancement
    - text: string                    # "Use Zod not Joi for validation"
      signal_type: string             # user_corrected | pattern_detected | agent_asked
      signals_count: integer          # How many signals triggered this (threshold: 5+)
      confidence: string              # high | medium | low
      threshold_reached_date: ISO8601 datetime  # When 5+ signals accumulated
      signals: [string]               # Task IDs supporting this rule

# ══════════════════════════════════════════════════════════════
# PLUGINS — Extensions that provide commands, hooks, MCPs, skills
# ══════════════════════════════════════════════════════════════

plugins:
  - name: string                      # Plugin name (unique per agent)
    source: string                    # marketplace | github:owner/repo | local:./path
    enabled: boolean                  # Whether to load this plugin's features
    version: string                   # "1.2.3" (marketplace/github) or "dev" (local)
    auto_update: boolean              # Auto-update when new versions available?
    installed_date: ISO8601 datetime
    installation_status: string       # installed | failed | outdated

# Plugin provides (Bridge auto-integrates):
#   - Commands: /review /test /lint /commit
#   - Hooks: pre_tool_use[bash], post_tool_use[write], etc.
#   - MCPs: github, postgres, playwright, etc.
#   - Skills: code review, testing, documentation

# ══════════════════════════════════════════════════════════════
# REPORTING — How results shown to user
# ══════════════════════════════════════════════════════════════

reporting:
  style: string                       # brief | summary | detailed

  on_complete:                        # What to include in success message
    - string                          # Options: summary | files_changed | test_results | commands_run

  on_error:                           # What to include in error message
    - string                          # Options: error_message | what_was_tried | suggested_fix

  on_permission_needed:               # What to include in permission request
    - string                          # Options: action_description | risk_level | file_preview

  on_progress:                        # For long-running tasks
    enabled: boolean
    interval_minutes: integer         # Show progress every N minutes

# ══════════════════════════════════════════════════════════════
# MEMORY — Context that persists and helps agent
# ══════════════════════════════════════════════════════════════

memory:
  known_issues:
    - description: string             # e.g., "Payment webhook times out after 30s"
      workaround: string              # How to avoid
      observed_count: integer         # How many times seen

  frequent_tasks:
    - task: string                    # e.g., "fix auth bugs"
      count: integer                  # How many times done
      avg_duration_minutes: integer
      success_rate: float             # 0.0-1.0

# ══════════════════════════════════════════════════════════════
# INTERNAL — Bridge-managed, user shouldn't touch
# ══════════════════════════════════════════════════════════════

_internal:
  last_checksum: string               # SHA256 of profile (detect corruption)
  backups:
    - version: integer
      date: ISO8601 datetime
      location: string                # Path to backup file

  enhancement_history:                # Log of past enhancements
    - version: integer
      date: ISO8601 datetime
      changes: [string]               # What was enhanced: ["Added rule: Use Zod", ...]
      triggered_by: string            # threshold | manual | admin
      signal_types: [string]          # Which signal types triggered: [user_corrected, pattern_detected]
      approved_by: string             # user | auto
```

---

## 2. Profile Manager

### 2.1 Creation Strategy: Template First, Then Enhance

```python
# Pseudocode showing the flow

def create(agent_name, project_path, template="coder-fullstack", hard_rules=None):
    # STEP 1: Validate inputs (always)
    validate_agent_name(agent_name)           # Unique, alphanumeric
    validate_project_path(project_path)       # Must exist

    # STEP 2: Load template and initialize profile
    base_profile = load_template(template)    # Get template defaults

    profile = Profile(
        name=agent_name,
        version=1,
        created=datetime.now(),
        base_template=template,

        identity=Identity(
            role=base_profile.identity.role,
            display_name=base_profile.identity.display_name,
            project=project_path,
            description=base_profile.identity.description
        ),

        context=Context(
            stack=[],                          # Empty, will enhance
            key_files=[]
        ),

        rules=Rules(
            hard=hard_rules or [],
            soft=base_profile.rules.soft       # Template soft rules
        ),

        plugins=base_profile.plugins,
        skills=base_profile.skills,
        reporting=base_profile.reporting,
        memory=base_profile.memory,

        _internal=Internal(
            last_checksum="",
            backups=[],
            enhancement_history=[]
        )
    )

    # STEP 3: OPTIONAL enhancement — try ProjectScanner
    try:
        scanner = ProjectScanner()
        context = scanner.scan(project_path, timeout=10)

        # Merge scanner findings (don't replace template)
        if context.stack:
            profile.context.stack = context.stack
        if context.key_files:
            profile.context.key_files.extend(context.key_files)
        if context.conventions:
            profile.context.conventions = context.conventions

    except Exception as e:
        # Scanner failed, but profile still valid
        logger.warning(f"ProjectScanner failed: {e}")
        # Continue with template defaults

    # STEP 4: Return profile (with or without enhancements)
    return profile
```

### 2.1 Core Responsibilities

```python
class ProfileManager:
    """
    Manage profile.yaml lifecycle.

    Responsible for:
    - Loading with validation
    - Saving with version tracking
    - Creating from templates
    - Validating schema and constraints
    - Detecting corruption and recovering
    """

    def load(agent_name: str,
             skip_validation: bool = False) -> Profile:
        """
        Load profile.yaml for agent.

        Args:
            agent_name: Name of agent (e.g., "coder-my-app")
            skip_validation: Skip expensive validation checks?

        Returns:
            Profile object (dataclass/Pydantic model)

        Process:
            1. Check if ~/.claude-bridge/agents/{agent_name}/ exists
            2. Load profile.yaml
            3. Validate YAML syntax
            4. Validate against schema
            5. Check integrity (checksum vs _internal.last_checksum)
            6. Return Profile

        Raises:
            ProfileNotFound: Agent doesn't exist
            InvalidYAML: File not valid YAML
            ValidationError: Schema/constraint violations
            CorruptedProfile: Checksum mismatch (attempt recovery)
        """
        pass

    def save(profile: Profile,
             force: bool = False) -> SaveResult:
        """
        Save profile.yaml, incrementing version.

        Args:
            profile: Profile object to save
            force: Skip validation and just save?

        Returns:
            SaveResult with:
            - success: bool
            - previous_version: int
            - new_version: int
            - checksum: str

        Process:
            1. Validate profile (unless force=True)
            2. Create backup of current profile
            3. Increment version number
            4. Calculate SHA256 checksum
            5. Write to profile.yaml
            6. Verify file written correctly
            7. Update _internal.backups
            8. Return success

        Raises:
            ValidationError: Profile invalid
            IOError: Can't write
        """
        pass

    def create(agent_name: str,
               project_path: str,
               template: str = "coder-fullstack",
               hard_rules: list[str] = None) -> Profile:
        """
        Create new profile from template.

        Args:
            agent_name: Unique name for agent
            project_path: Absolute path to project
            template: Base template to use
            hard_rules: User's critical rules (from onboarding Q3)

        Returns:
            Profile object (not yet saved)

        Process:
            1. Validate inputs (agent name exists, is unique)
            2. Validate project_path exists
            3. Load template from templates/
            4. Initialize profile with template defaults:
               - name, identity.project, identity.role, rules.hard
               - plugins, skills, reporting, memory (all from template)
               - context: { stack: [], key_files: [] }
            5. OPTIONAL: Try to enhance with ProjectScanner:
               - Scan project for stack detection
               - Add detected technologies to context.stack
               - Add detected reference files to context.key_files
               - If scanner fails/times out: proceed with template defaults
            6. Set metadata (version=1, created=now)
            7. Return Profile (not saved)

        Key principle:
            - Profile ALWAYS created (never fails due to ProjectScanner)
            - Template provides working defaults
            - Scanner findings enhance (don't replace) defaults
            - New projects with no files still get valid profile

        Note: Caller must call save() to persist

        Raises:
            TemplateNotFound: Template doesn't exist
            ValidationError: agent_name invalid or already exists
            ProjectPathInvalid: project_path doesn't exist
        """
        pass

    def create_custom_template(template_name: str,
                             source_template: str = "coder-fullstack") -> Template:
        """
        Create custom template by cloning and modifying existing template.

        Args:
            template_name: Name of new template (e.g., "my-backend-dev")
            source_template: Template to clone from (default: coder-fullstack)

        Returns:
            Template object (not yet saved)

        Process:
            1. Load source template
            2. Clone it
            3. Return for user to edit
            4. User saves via /save-template

        Raises:
            TemplateNotFound: source_template doesn't exist
        """
        pass

    def save_template(template_name: str,
                     template: Template) -> bool:
        """
        Save custom template locally.

        Location: ~/.claude-bridge/templates/{template_name}.yaml

        Process:
            1. Validate template (required fields present)
            2. Write to ~/.claude-bridge/templates/{template_name}.yaml
            3. Log save
            4. Return success

        Raises:
            ValidationError: Template invalid
            IOError: Can't write
        """
        pass

    def export_profile_as_template(agent_name: str,
                                  template_name: str) -> bool:
        """
        Export working agent profile as reusable template.

        Purpose: User has working agent, wants to make it a standard template.

        Args:
            agent_name: Agent to export from
            template_name: New template name

        Process:
            1. Load agent profile
            2. Remove instance-specific fields:
               - name (unique per agent)
               - identity.project (per-project)
               - context (per-project)
               - created, last_enhanced (per-instance)
               - _internal (auto-managed)
            3. Keep reusable fields:
               - identity.role, display_name
               - plugins, skills
               - rules.soft (learned patterns)
               - reporting preferences
            4. Save to ~/.claude-bridge/templates/{template_name}.yaml
            5. Log export

        Raises:
            ProfileNotFound: Agent doesn't exist
            ValidationError: Can't convert to template
        """
        pass

    def list_templates(source: str = "local") -> list[TemplateInfo]:
        """
        List available templates.

        Args:
            source: "local" (user created) | "builtin" (included with Bridge)

        Returns:
            [TemplateInfo] with template_name, role, description, creator
        """
        pass

    def delete_template(template_name: str) -> bool:
        """Delete custom template."""
        pass

    def get_template(template_name: str) -> Template:
        """
        Load profile template (local or built-in).

        Resolution order:
        1. Check LOCAL: ~/.claude-bridge/templates/{template_name}.yaml
        2. Check BUILT-IN: claude_bridge/templates/{template_name}.yaml

        Local templates override built-in templates.

        Built-in templates:
        - coder-fullstack: Full-stack dev, write code
        - coder-focused: Bug fixing, narrow scope
        - researcher: Web research, synthesis
        - reviewer: Code review only
        - devops: Infra, deployment
        - writer: Docs, content
        - analyst: Data analysis

        Raises:
            TemplateNotFound: No template found in local or built-in
        """
        pass

    def validate(profile: Profile,
                 strict: bool = True) -> ValidationResult:
        """
        Validate profile structure and constraints.

        Args:
            strict: Fail on warnings or only errors?

        Returns:
            ValidationResult with:
            - is_valid: bool
            - errors: [str]           # Must fix
            - warnings: [str]         # Should fix
            - suggestions: [str]      # Nice to have

        Checks:
            - All required fields present
            - Field types match schema
            - Paths exist (project, key_files)
            - No duplicate hard rules
            - Hard rules don't conflict
            - Plugins exist (if specified)
            - No circular dependencies
            - Role is valid
            - Soft rules have signals_count >= 5 or threshold_reached_date
            - key_files contains reference files (docs, configs), not code files
            - Checksum matches previous save (corruption detection)
        """
        pass

    def update_metadata(profile: Profile,
                       **kwargs) -> Profile:
        """
        Update metadata fields safely.

        Allowed fields: display_name, description, reporting, memory, etc.
        Forbidden: name (immutable), version (managed by save())

        Returns:
            Updated profile (not saved)
        """
        pass

    def list_profiles() -> list[ProfileInfo]:
        """
        List all profiles on machine.

        Returns:
            [ProfileInfo] with agent_name, role, project, version, last_enhanced
        """
        pass

    def delete(agent_name: str,
               confirm: bool = True) -> bool:
        """
        Delete agent and all its data.

        Args:
            confirm: Ask user to confirm?

        Process:
            1. Create backup (keep for 30 days)
            2. Delete ~/.claude-bridge/agents/{agent_name}/
            3. Log deletion
            4. Return success

        Safety: Always backup before delete
        """
        pass
```

### 2.2 Error Handling

```python
class ProfileLoadError(Exception):
    """Raised when profile can't be loaded."""
    def __init__(self, agent_name: str, reason: str, recovery_attempted: bool):
        self.agent_name = agent_name
        self.reason = reason
        self.recovery_attempted = recovery_attempted
        super().__init__(f"Failed to load {agent_name}: {reason}")

class CorruptedProfile(ProfileLoadError):
    """Profile file is corrupted (YAML invalid, missing fields, etc.)"""
    def __init__(self, agent_name: str, error: str, backup_available: bool):
        super().__init__(agent_name, error, backup_available)
        self.backup_available = backup_available
```

---

## 3. Project Scanner

### 3.1 Purpose

Analyze project structure to auto-populate profile context. Should be **smart but defensive**:
- Detect common stacks (Node, Python, Go, etc.)
- Find key directories and files
- Extract conventions from config files
- Estimate criticality of files

### 3.2 Scanner Class

```python
class ProjectScanner:
    """Analyze project to populate profile context."""

    def scan(project_path: str,
             timeout: int = 30) -> ProjectContext:
        """
        Scan project and extract context.

        Args:
            project_path: Absolute path to project
            timeout: Max seconds to scan (defensive against huge repos)

        Returns:
            ProjectContext with:
            - stack: detected technologies
            - key_dirs: important directories
            - critical_files: important files
            - conventions: coding conventions
            - structure: project structure overview

        Process:
            1. Validate project_path exists
            2. Check for git repo
            3. Detect stack (package.json, requirements.txt, etc.)
            4. Find key directories based on stack
            5. Extract conventions (.eslintrc, Makefile, etc.)
            6. Identify critical files
            7. Return context (or partial context if timeout)

        Safety:
            - If scan times out, return what was found so far
            - Never recurse into .git, node_modules, etc.
            - Skip symlinks (prevent infinite loops)
            - Large repos (>10GB) → warn user
        """
        pass

    def _detect_stack(project_path: str) -> StackInfo:
        """
        Detect tech stack from config files.

        Checks (in order):
        1. package.json → parse, extract dependencies
           - nextjs, react, vue, svelte → frontend framework
           - express, fastify, koa → backend framework
           - typescript → language
           - prisma, sequelize, typeorm → ORM
           - jest, vitest, mocha → test framework
           - webpack, vite, esbuild → bundler

        2. requirements.txt / pyproject.toml → python stack
           - django, flask, fastapi → framework
           - sqlalchemy, django.db → ORM
           - pytest, unittest → testing

        3. go.mod → go stack
           - Extract module name
           - Check for common packages

        4. Dockerfile → containerization
        5. docker-compose.yml → services (postgres, redis, etc.)
        6. .github/workflows → CI/CD system

        Returns:
            StackInfo with list of technologies
        """
        pass

    def _detect_key_dirs(project_path: str,
                        stack: StackInfo) -> list[DirInfo]:
        """
        Identify important directories.

        Heuristics:
        - Stack-specific: src/components, src/utils, tests/, migrations/
        - Convention-based: auth/, api/, models/, services/
        - Domain-specific: payments/, orders/, notifications/

        For each dir, assign reason:
        - "authentication logic"
        - "API endpoints"
        - "payment processing"
        - "test suite"

        Returns:
            [DirInfo] sorted by importance
        """
        pass

    def _detect_critical_files(project_path: str,
                              stack: StackInfo) -> list[FileInfo]:
        """
        Identify REFERENCE FILES agent should know about.

        NOT code files (too noisy) — only docs, configs, schemas.

        Always critical:
        - package.json / pyproject.toml (dependencies)
        - docker-compose.yml (services)
        - .env.example (environment setup)
        - README.md (project overview)

        Stack-specific:
        - prisma/schema.prisma (DB schema)
        - tsconfig.json (TypeScript config)
        - docker-compose.yml (service setup)
        - .github/workflows (CI config)

        Documentation files (if exist):
        - docs/*.md (architecture, guides)
        - ARCHITECTURE.md (system design)

        Domain-specific (infer from dir names):
        - If payments/ exists → suggest docs/payment-flow.md as sensitive

        Returns:
            [FileInfo] with path, reason, sensitivity
        """
        pass

    def _detect_conventions(project_path: str) -> Conventions:
        """
        Extract coding conventions from config.

        Checks:
        - .eslintrc → linting rules (e.g., "no-any")
        - .prettierrc → formatting (spaces vs tabs)
        - pyproject.toml [tool.ruff] → Python linting
        - .github/workflows → CI commands (e.g., "npm test")
        - Makefile → build commands
        - tsconfig.json → TypeScript strictness

        Returns:
            Conventions object with detected patterns
        """
        pass
```

### 3.3 Data Structures

```python
@dataclass
class ProjectContext:
    path: str
    stack: StackInfo
    key_dirs: list[DirInfo]
    critical_files: list[FileInfo]
    conventions: Conventions

@dataclass
class StackInfo:
    technologies: list[str]           # [nextjs, typescript, prisma]
    frameworks: list[str]
    languages: list[str]
    databases: list[str]

@dataclass
class DirInfo:
    path: str                         # relative to project root
    reason: str                       # why important
    importance: str                   # critical | high | medium
    domain: str                       # optional: auth, payments, api

@dataclass
class FileInfo:
    path: str                         # relative to project root
    reason: str
    sensitive: bool
    importance: str                   # critical | high | medium

@dataclass
class Conventions:
    linter: str                       # eslint | ruff | golint
    formatter: str                    # prettier | black | gofmt
    test_framework: str               # jest | pytest | go test
    test_command: str                 # e.g., "npm test"
    build_command: str                # e.g., "npm run build"
    ci_system: str                    # github | gitlab | circle
```

---

## 4. Design Decisions

### Template-First Profile Creation

**Decision:** Generate profile from template FIRST, then optionally enhance with ProjectScanner.

**Why:** Ensures profile always exists, even if project has no files or scanner fails.

**Flow:**
1. Load template (has working defaults)
2. Initialize profile with template + user input
3. Try ProjectScanner (best-effort enhancement)
4. If scanner succeeds: merge findings into profile
5. If scanner fails: profile still valid with template defaults

**Benefits:**
- ✅ New projects work immediately (even with no files)
- ✅ No dependency on ProjectScanner success
- ✅ Profile always has usable defaults
- ✅ Scanner findings enhance (don't replace)

**Example:**

```yaml
# New project with no files

Project: ~/new-app/ (just created, almost empty)
  ├── .git/
  ├── .gitignore
  └── README.md

# Bridge creates profile:
context:
  stack: []                    # ← Scanner couldn't detect, so empty
  key_files: []               # ← No reference files to find

# But from template, profile includes:
rules.soft: ["Write tests first", "Commit after each feature"]
plugins: [...]
skills: [review, test, commit]
memory: []

# Profile is valid and usable despite empty context
```

As project grows and agent works:
- ProjectScanner re-runs later → detects stack → context updates
- Enhancement accumulates signals → adds soft rules + known_issues
- User manually adds key_files → builds up reference docs

---

### Custom Templates (Local Only, MVP)

**Decision:** Support custom templates stored locally, not shared team templates in MVP.

**Why:** Simpler to implement, covers individual developer needs. Team templates (Phase 2+).

**How:**
1. **Local templates** stored in `~/.claude-bridge/templates/`
2. **Resolution order:** Local → Built-in
3. **Creation methods:**
   - `/create-template my-backend-dev --from coder-fullstack` (clone + edit)
   - `/save-as-template coder-my-app → my-standard` (export working agent)
   - Manual YAML file creation

**Example:**

```bash
# User has working backend agent: coder-my-app
# Decides to standardize it as template

/save-as-template coder-my-app → my-backend-standard
# Saves to ~/.claude-bridge/templates/my-backend-standard.yaml

# Next time:
/new-agent
→ Role: Developer
→ Template: my-backend-standard (shows in list if starts with role prefix)
→ Agent created with user's standardized config
```

**What's Stored in Templates:**
- ✅ identity.role, display_name (the purpose)
- ✅ plugins (tools for this role)
- ✅ skills (commands for this role)
- ✅ rules.soft (learned conventions)
- ✅ reporting preferences

**What's NOT Stored:**
- ❌ agent name (instance-specific)
- ❌ identity.project (instance-specific)
- ❌ context (project-specific)
- ❌ _internal metadata (auto-managed)

---

### key_files: Reference Files Only, Not Code Files

**Decision:** key_files should contain only **important reference files** (docs, configs, schemas).
NOT code files that agent frequently edits.

**Why:** Tracking every `.ts` file agent touches becomes noise/maintenance burden over time.

**Examples of what SHOULD be in key_files:**
- `prisma/schema.prisma` (DB schema to read)
- `docs/payment-flow.md` (architecture guide)
- `.env.example` (env variable reference)
- `README.md` (project overview)

**Examples of what should NOT be in key_files:**
- `src/auth/session.ts` (code file, agent edits frequently)
- `src/api/routes.ts` (code file)
- `src/components/Button.tsx` (code file)

**How files get added:**
1. **Onboarding:** ProjectScanner detects reference files
2. **Enhancement:** If agent asks about topic 5+ times → suggest relevant docs
   - Example: Agent asks "What's payment flow?" 5 times → suggest `docs/payment-flow.md`
3. **Manual:** User can add reference files they want agent to know about

---

## 5. Success Criteria

Profile system complete when:

- [x] Schema defined (clean YAML structure, no redundancy)
- [x] ProfileManager loads/saves/validates correctly
- [x] Profile version increments on save
- [x] Checksum prevents corruption
- [x] Corruption detected and recovery attempted
- [x] ProjectScanner detects common stacks
- [x] ProjectScanner finds reference files (not code files)
- [x] ProjectScanner extracts conventions
- [x] Profiles created from templates (template-first approach)
- [x] Custom templates can be created locally
- [x] Agents can be exported as templates
- [x] Local templates override built-in templates
- [x] Template resolution: local → built-in
- [x] Validation shows clear error messages
- [x] All operations idempotent
- [x] Backup/restore works
- [x] User data never lost
- [x] No redundancy (plugins provide hooks/skills, not profile)
- [x] Soft rules track signals_count and threshold_reached_date
- [x] learned_patterns removed (merged into key_files reason)
- [x] key_files contains reference files, not code files
- [x] Template-first profile creation (template provides base, scanner enhances)
