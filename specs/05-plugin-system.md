# Plugin System Specification

## Overview

Claude Bridge manages Claude Code extensions as **plugins**. A plugin is a packaged set of:
- **Commands** — Slash commands (`/review`, `/test`, `/commit`)
- **Hooks** — Event handlers (`pre_tool_use`, `post_tool_use`, `stop`)
- **MCP Servers** — External integrations (GitHub, Postgres, Playwright, etc.)
- **Skills** — Instruction sets (specific workflows)
- **Agents** — Specialized sub-agents

## 1. Plugin Sources

Plugins can come from three sources:

### 1.1 Official Marketplace
- URL: `https://claudemarketplaces.com/`
- Install: `/plugin install plugin-name@marketplace`
- Example: `typescript-linter`, `git-automation`

### 1.2 GitHub Repositories
- Format: `github:{owner}/{repo}`
- Install: `/plugin install {owner}/{repo}`
- Requirements: repo contains `plugins/plugin.yaml` or `marketplace.json`
- Example: `github:myorg/claude-reviewer` → installs from GitHub

### 1.3 Local Directory
- Format: `local:{path}`
- Install: `/plugin install ./plugins/custom-helper`
- Requirements: directory contains `plugin.yaml`
- Example: `local:./plugins/linter` → uses local files

---

## 2. Plugin Structure

### 2.1 Plugin Package (plugin.yaml)

Each plugin contains a `plugin.yaml` describing what it provides:

```yaml
# ./plugins/typescript-linter/plugin.yaml
name: typescript-linter
version: 1.0.0
author: myorg
description: "ESLint + Prettier for TypeScript projects"

dependencies:
  - eslint
  - prettier

provides:
  commands:
    - name: lint
      description: "Run ESLint on project"
      script: ./commands/lint.sh

    - name: format
      description: "Format with Prettier"
      script: ./commands/format.sh

  hooks:
    - type: post_tool_use
      event: write
      script: ./hooks/post-write-lint.py

    - type: pre_tool_use
      event: bash
      script: ./hooks/pre-bash-validate.py

  skills:
    - name: typescript-best-practices
      description: "TS coding standards"
      file: ./skills/ts-best-practices.md

  mcp_servers:
    - name: eslint-mcp
      type: stdio
      command: "node ./mcp/eslint-server.js"

  agents:
    - name: ts-reviewer
      description: "Reviews TypeScript code"
      instruction_file: ./agents/ts-reviewer.md
```

### 2.2 Plugin Installation Structure

After installation, plugin lives at:
```
~/.claude-bridge/plugins/
├── typescript-linter/
│   ├── plugin.yaml              # Metadata
│   ├── commands/
│   │   ├── lint.sh
│   │   └── format.sh
│   ├── hooks/
│   │   ├── post-write-lint.py
│   │   └── pre-bash-validate.py
│   ├── skills/
│   │   └── ts-best-practices.md
│   ├── mcp/
│   │   └── eslint-server.js
│   ├── agents/
│   │   └── ts-reviewer.md
│   └── package.json             # Dependencies
```

---

## 3. Profile Declaration

### 3.1 Plugin Section in profile.yaml

```yaml
plugins:
  - name: typescript-linter
    source: marketplace              # marketplace | github | local
    enabled: true
    version: "1.0.0"

  - name: custom-reviewer
    source: github:myorg/claude-reviewer
    enabled: true
    version: "2.1.3"
    auto_update: true               # Auto-update available versions

  - name: local-helper
    source: local:./plugins/helper
    enabled: true
    version: "dev"                  # No versioning for local
```

### 3.2 Enabled/Disabled Plugins

Plugins can be disabled without uninstalling:
```yaml
plugins:
  - name: typescript-linter
    enabled: false                  # Won't load commands/hooks/MCPs
```

---

## 4. Plugin Manager

### 4.1 Responsibilities

```python
class PluginManager:
    """Manage plugin discovery, installation, and integration."""

    def discover(source: str) -> list[PluginInfo]:
        """
        Discover available plugins from source.

        Args:
            source: "marketplace" | "github:owner/repo" | "local:path"

        Returns:
            list[PluginInfo] with name, version, description

        Process:
            - Marketplace: Fetch from CDN or GitHub (cached)
            - GitHub: Fetch marketplace.json or plugin.yaml
            - Local: Scan directory for plugin.yaml files
        """
        pass

    def install(agent_name: str,
                plugin_source: str,
                version: str = "latest") -> PluginInfo:
        """
        Install plugin for agent.

        Args:
            plugin_source: "name@marketplace" | "owner/repo" | "./path"
            version: Specific version or "latest"

        Returns:
            PluginInfo (installed plugin metadata)

        Process:
            1. Validate plugin exists
            2. Check dependencies available
            3. Download/copy plugin files
            4. Register in profile.yaml
            5. Integrate into settings.json (hooks, MCP servers)
            6. Log install

        Raises:
            PluginNotFound, DependencyError, InstallError
        """
        pass

    def uninstall(agent_name: str, plugin_name: str) -> None:
        """
        Uninstall plugin (and remove from profile).

        Process:
            1. Remove from profile.yaml
            2. Remove from settings.json (hooks, MCPs)
            3. Delete plugin files (keep in trash first?)
            4. Regenerate agent config
        """
        pass

    def enable(agent_name: str, plugin_name: str) -> None:
        """
        Enable plugin (add hooks/commands back to settings).
        """
        pass

    def disable(agent_name: str, plugin_name: str) -> None:
        """
        Disable plugin (remove hooks/commands from settings).
        """
        pass

    def list_installed(agent_name: str) -> list[PluginInfo]:
        """List all plugins for agent."""
        pass

    def get_updates(agent_name: str) -> list[PluginUpdate]:
        """
        Check for available updates.

        Returns:
            list[PluginUpdate] with plugin_name, current_version, available_version
        """
        pass

    def update(agent_name: str, plugin_name: str,
               version: str = "latest") -> PluginInfo:
        """
        Update plugin to new version.

        Process:
            1. Verify update available
            2. Backup current version (state recovery)
            3. Download new version
            4. Test compatibility (dry-run hooks?)
            5. Update profile.yaml
            6. Regenerate agent config
            7. If fails: restore from backup

        Rollback on failure: automatic
        """
        pass

    def validate(plugin_path: str) -> ValidationResult:
        """
        Validate plugin structure before installation.

        Checks:
            - plugin.yaml exists and valid YAML
            - Required fields present (name, version, provides)
            - Scripts executable
            - Dependencies declared
            - No name conflicts with existing plugins
        """
        pass
```

### 4.2 Dependency Resolution

```python
class DependencyResolver:
    """Resolve and validate plugin dependencies."""

    def resolve(agent_name: str,
                plugin_source: str) -> DependencyGraph:
        """
        Resolve all dependencies for a plugin.

        Returns:
            DependencyGraph with:
            - direct: plugins this directly depends on
            - transitive: all dependencies
            - conflicts: any version conflicts
            - missing: unresolved dependencies

        If conflicts → raise DependencyError with suggestions
        """
        pass

    def check_available() -> dict:
        """
        Check which system dependencies are available.

        Returns:
            { "nodejs": "18.0.0", "python": "3.11", ... }
        """
        pass
```

---

## 5. Plugin Integration into Agent Config

### 5.1 Auto-Generate settings.json

When profile.yaml changes (plugin added/removed/enabled/disabled):

```python
class ConfigGenerator:

    def regenerate_settings(agent_name: str) -> None:
        """
        Regenerate agent's settings.json from profile + plugins.

        Process:
            1. Load profile.yaml
            2. For each enabled plugin:
               - Read plugin.yaml
               - Extract hooks → add to settings.json
               - Extract MCP servers → add to settings.json
               - Extract commands → register
            3. Write settings.json
            4. Keep user's manual edits (merge, not replace)

        Safety:
            - Keep backup of previous settings.json
            - Validate generated config before writing
            - Warn if overwrites manual edits
        """
        pass
```

### 5.2 Example Output (settings.json)

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "tool": "write",
        "script": "~/.claude-bridge/plugins/typescript-linter/hooks/post-write-lint.py"
      }
    ],
    "PreToolUse": [
      {
        "tool": "bash",
        "script": "~/.claude-bridge/plugins/typescript-linter/hooks/pre-bash-validate.py"
      }
    ]
  },
  "mcp_servers": [
    {
      "name": "eslint-mcp",
      "type": "stdio",
      "command": "node ~/.claude-bridge/plugins/typescript-linter/mcp/eslint-server.js"
    }
  ],
  "commands": [
    {
      "name": "lint",
      "source": "typescript-linter",
      "script": "~/.claude-bridge/plugins/typescript-linter/commands/lint.sh"
    }
  ]
}
```

---

## 6. Plugin Marketplace Discovery

### 6.1 Marketplace.json

Marketplace (official or GitHub repo) hosts `marketplace.json`:

```json
{
  "plugins": [
    {
      "name": "typescript-linter",
      "description": "ESLint + Prettier for TypeScript",
      "version": "1.0.0",
      "author": "anthropic",
      "url": "https://github.com/anthropic/claude-typescript-linter",
      "installs": 1250,
      "rating": 4.8
    },
    {
      "name": "git-automation",
      "description": "Git workflows and automation",
      "version": "2.0.0",
      "author": "community",
      "url": "https://github.com/user/claude-git",
      "installs": 450,
      "rating": 4.5
    }
  ]
}
```

### 6.2 Plugin Discovery Flow

```python
class MarketplaceClient:

    def search(query: str) -> list[PluginInfo]:
        """
        Search marketplace.

        Process:
            1. Check local cache (5-minute TTL)
            2. If miss: fetch from CDN/GitHub
            3. Filter by query
            4. Sort by rating + installs
            5. Return top N results
        """
        pass

    def get_plugin_info(plugin_name: str,
                        marketplace: str = "official") -> PluginInfo:
        """
        Get detailed info about plugin (readme, version history, etc.).
        """
        pass
```

---

## 7. Enhancement Through Plugins

As Bridge learns (enhancement signals accumulate), it can **suggest plugin additions**:

```yaml
# enhancement-accumulator.yaml
plugin_suggestions:
  - type: pattern_detected
    content: "Agent always runs npm test — suggest @typescript-linter?"
    proposed_plugin: typescript-linter@marketplace
    confidence: high
    signals_supporting: [task_001, task_003, task_005]
```

When enhancement triggers:
```
Found plugin suggestions:

🟢 typescript-linter (high confidence)
   "You run 'npm test' in 5 tasks — this plugin automates linting"

[✅ Install] [👁️ Preview] [❌ Skip]
```

---

## 8. Error Handling & Recovery

### 8.1 Plugin Installation Failures

| Error | Recovery |
|---|---|
| Plugin not found | Suggest alternatives from marketplace |
| Dependency missing | List missing deps, suggest install |
| Hook script fails | Log error, disable hook, warn user |
| MCP server won't start | Log startup error, mark as unhealthy |
| Version conflict | List conflicts, ask user to resolve |

### 8.2 Graceful Degradation

- Plugin install fails → Agent still works, just without that plugin's features
- Hook fails → Log and continue (don't block task)
- MCP server offline → Available tools reduced, no crash
- Plugin update fails → Rollback to previous version, try again later

---

## 9. Testing

### 9.1 Unit Tests
- PluginManager: install, uninstall, enable, disable
- DependencyResolver: resolve, check conflicts
- MarketplaceClient: search, fetch plugin info
- ConfigGenerator: generate settings.json correctly

### 9.2 Integration Tests
- Install plugin → commands available in agent
- Install plugin → hooks fire correctly
- Install plugin → MCP servers register
- Enable/disable → features toggle correctly
- Update plugin → backward compatibility maintained

### 9.3 Test Fixtures
- Mock marketplace.json
- Mock plugin packages (real files)
- Mock GitHub API responses
- Broken/malformed plugins (error cases)

---

## 10. Success Criteria

Plugin system is complete when:

- [x] Plugin schema defined (plugin.yaml)
- [x] PluginManager can install from marketplace/GitHub/local
- [x] Installed plugins integrate into settings.json
- [x] Commands/hooks/MCPs from plugins work correctly
- [x] Plugin enable/disable works (features toggle)
- [x] Dependencies resolved automatically
- [x] Installation failures handled gracefully
- [x] Plugin updates work with rollback on failure
- [x] Enhancement can suggest plugins to install
- [x] Comprehensive error messages for troubleshooting

