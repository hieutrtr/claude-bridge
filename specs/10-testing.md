# Testing Specification

## Overview

Comprehensive testing strategy covering unit, integration, and system tests.

**Principle:** Test-driven approach. Write tests first, then implementation.

---

## 1. Test Structure

### 1.1 Directory Layout

```
claude-bridge/
├── tests/
│   ├── unit/
│   │   ├── test_profile_system.py
│   │   ├── test_context_generation.py
│   │   ├── test_enhancement_system.py
│   │   ├── test_agent_lifecycle.py
│   │   ├── test_plugin_system.py
│   │   ├── test_permission_system.py
│   │   ├── test_channels.py
│   │   └── test_data_structures.py
│   │
│   ├── integration/
│   │   ├── test_profile_to_claude_md.py
│   │   ├── test_signal_to_enhancement.py
│   │   ├── test_task_execution.py
│   │   ├── test_permission_flow.py
│   │   └── test_full_workflow.py
│   │
│   ├── fixtures/
│   │   ├── mock_profiles.py
│   │   ├── mock_projects.py
│   │   ├── mock_signals.py
│   │   ├── mock_claude_code.py
│   │   └── mock_telegram.py
│   │
│   └── conftest.py              # Pytest fixtures
```

### 1.2 Test Naming Convention

```
test_{component}_{function}_{scenario}.py

Examples:
- test_profile_manager_load_valid_profile.py
- test_profile_manager_load_corrupted_profile.py
- test_enhancement_engine_generate_proposal_user_corrected.py
- test_agent_manager_spawn_headless_mode.py
```

---

## 2. Unit Tests

### 2.1 Profile System Tests

```python
# tests/unit/test_profile_system.py

class TestProfileManager:
    """Test ProfileManager class."""

    def test_load_valid_profile(self, valid_profile_path):
        """Load valid profile.yaml"""
        pm = ProfileManager()
        profile = pm.load("coder-my-app")
        assert profile.name == "coder-my-app"
        assert profile.version == 1

    def test_load_nonexistent_profile(self):
        """Loading nonexistent profile raises error"""
        pm = ProfileManager()
        with pytest.raises(ProfileNotFound):
            pm.load("nonexistent-agent")

    def test_load_invalid_yaml(self, invalid_yaml_path):
        """Loading invalid YAML raises error"""
        pm = ProfileManager()
        with pytest.raises(InvalidYAML):
            pm.load("broken-agent")

    def test_load_with_recovery(self, corrupted_profile_path):
        """Loading corrupted profile attempts recovery"""
        pm = ProfileManager()
        profile = pm.load("corrupted-agent")
        assert profile is not None  # Recovered
        # Check backup was used
        assert has_backup("corrupted-agent")

    def test_save_increments_version(self, temp_profile):
        """Saving profile increments version"""
        pm = ProfileManager()
        original_version = temp_profile.version
        pm.save(temp_profile)
        assert temp_profile.version == original_version + 1

    def test_save_idempotent(self, temp_profile):
        """Saving same profile twice is safe"""
        pm = ProfileManager()
        pm.save(temp_profile)
        first_version = temp_profile.version
        pm.save(temp_profile)  # Save again with same content
        assert temp_profile.version == first_version + 1  # Version still increments

    def test_validate_required_fields(self):
        """Validation catches missing required fields"""
        invalid = Profile(name=None)  # Missing required field
        result = pm.validate(invalid)
        assert not result.is_valid
        assert "name" in result.errors

    def test_validate_paths_exist(self, nonexistent_path):
        """Validation checks project path exists"""
        profile = Profile(project=nonexistent_path)
        result = pm.validate(profile)
        assert not result.is_valid

    def test_create_from_template(self, mock_project_path):
        """Creating agent from template works"""
        pm = ProfileManager()
        profile = pm.create(
            "coder-my-app",
            mock_project_path,
            template="coder-fullstack",
            hard_rules=["No push to main"]
        )
        assert profile.name == "coder-my-app"
        assert profile.version == 1
        assert "No push to main" in [r.text for r in profile.rules.hard]

class TestProjectScanner:
    """Test ProjectScanner class."""

    def test_detect_node_stack(self, node_project_path):
        """Detect Node.js stack from package.json"""
        scanner = ProjectScanner()
        context = scanner.scan(node_project_path)
        assert "nextjs" in context.stack.technologies
        assert "typescript" in context.stack.technologies
        assert "prisma" in context.stack.technologies

    def test_detect_python_stack(self, python_project_path):
        """Detect Python stack from requirements.txt"""
        scanner = ProjectScanner()
        context = scanner.scan(python_project_path)
        assert "django" in context.stack.technologies
        assert "postgres" in context.stack.databases

    def test_detect_key_dirs(self, sample_project_path):
        """Scanner identifies key directories"""
        scanner = ProjectScanner()
        context = scanner.scan(sample_project_path)
        paths = [d.path for d in context.key_dirs]
        assert "src/auth" in paths
        assert "src/api" in paths

    def test_detect_critical_files(self, sample_project_path):
        """Scanner identifies critical files"""
        scanner = ProjectScanner()
        context = scanner.scan(sample_project_path)
        paths = [f.path for f in context.critical_files]
        assert "package.json" in paths
        assert "README.md" in paths

    def test_scan_timeout(self, huge_project_path):
        """Scan respects timeout for huge repos"""
        scanner = ProjectScanner()
        context = scanner.scan(huge_project_path, timeout=1)
        assert context is not None  # Partial results

    def test_skip_git_and_node_modules(self, sample_project_path):
        """Scanner skips .git and node_modules"""
        scanner = ProjectScanner()
        context = scanner.scan(sample_project_path)
        paths = [d.path for d in context.key_dirs]
        assert ".git" not in paths
        assert "node_modules" not in paths
```

### 2.2 Context Generation Tests

```python
class TestClaudeMdGenerator:
    """Test CLAUDE.md generation."""

    def test_generate_project_level(self, mock_profile):
        """Generates valid project-level CLAUDE.md"""
        gen = ClaudeMdGenerator()
        content = gen.generate_project_level("coder-my-app")
        assert "# Agent: coder-my-app" in content
        assert "## 🎭 Role" in content
        assert "## 🔒 Rules" in content
        assert content.count("##") >= 5  # Has multiple sections

    def test_generate_layer_specific(self, mock_profile):
        """Generates layer-specific CLAUDE.md"""
        gen = ClaudeMdGenerator()
        content = gen.generate_layer_specific("coder-my-app", "src/payments")
        assert "⚠️ SENSITIVE AREA" in content
        assert "Payments" in content

    def test_validate_generated_markdown(self):
        """Generated markdown is valid"""
        gen = ClaudeMdGenerator()
        content = gen.generate_project_level("test-agent")
        result = validate_markdown(content)
        assert result.is_valid

    def test_template_variables_all_present(self):
        """All template variables provided"""
        gen = ClaudeMdGenerator()
        vars = gen._collect_variables("coder-my-app")
        assert vars.agent_name is not None
        assert vars.display_name is not None
        assert vars.stack_description is not None

    def test_change_detection_no_change(self, existing_claude_md):
        """No rewrite if content unchanged"""
        gen = ClaudeMdGenerator()
        new_content = gen.generate_project_level("test-agent")
        changed = gen.detector.has_changed(new_content, existing_claude_md)
        assert not changed

    def test_change_detection_with_change(self, existing_claude_md):
        """Detects when content changed"""
        new_content = "completely different content"
        changed = gen.detector.has_changed(new_content, existing_claude_md)
        assert changed

    def test_file_write_backup(self, temp_dir):
        """File write creates backup"""
        writer = FileWriter()
        result = writer.write(
            f"{temp_dir}/CLAUDE.md",
            "new content",
            backup_existing=True
        )
        assert result.success
        assert os.path.exists(f"{temp_dir}/CLAUDE.md.bak")

    def test_file_write_rollback_on_failure(self, readonly_dir):
        """Rollback on write failure"""
        writer = FileWriter()
        result = writer.write(f"{readonly_dir}/CLAUDE.md", "content")
        assert not result.success
        assert result.previous_content is not None  # Restored
```

### 2.3 Enhancement System Tests

```python
class TestEnhancementAccumulator:
    """Test signal accumulation."""

    def test_log_signal(self, temp_agent_dir):
        """Signal logged correctly"""
        acc = EnhancementAccumulator()
        signal = Signal(
            type=SignalType.USER_CORRECTED,
            task_id="task_001",
            content="User changed Joi to Zod"
        )
        acc.log_signal("test-agent", signal)
        loaded = acc.load_accumulator("test-agent")
        assert len(loaded.signals[SignalType.USER_CORRECTED]) == 1

    def test_threshold_detection(self, temp_agent_dir):
        """Detects when 5+ signals of same type"""
        acc = EnhancementAccumulator()
        for i in range(5):
            signal = Signal(type=SignalType.USER_CORRECTED, task_id=f"task_{i:03d}")
            acc.log_signal("test-agent", signal)

        thresholds_hit = acc.check_thresholds("test-agent")
        assert SignalType.USER_CORRECTED in thresholds_hit

    def test_idempotent_logging(self, temp_agent_dir):
        """Logging same signal twice is safe"""
        acc = EnhancementAccumulator()
        signal = Signal(type=SignalType.USER_CORRECTED, task_id="task_001")
        acc.log_signal("test-agent", signal)
        first_count = len(acc.load_accumulator("test-agent").signals[SignalType.USER_CORRECTED])
        acc.log_signal("test-agent", signal)  # Log again
        second_count = len(acc.load_accumulator("test-agent").signals[SignalType.USER_CORRECTED])
        # Should be deduplicated
        assert second_count == first_count

class TestEnhancementEngine:
    """Test proposal generation."""

    def test_generate_proposals_user_corrected(self, signals_user_corrected):
        """Generate proposal from user_corrected signals"""
        engine = EnhancementEngine()
        proposals = engine.generate_proposals("test-agent", [SignalType.USER_CORRECTED])
        assert len(proposals) > 0
        assert proposals[0].type == SignalType.USER_CORRECTED
        assert proposals[0].confidence == "high"

    def test_generate_proposals_agent_asked(self, signals_agent_asked):
        """Generate proposal from agent_asked signals"""
        engine = EnhancementEngine()
        proposals = engine.generate_proposals("test-agent", [SignalType.AGENT_ASKED])
        assert len(proposals) > 0
        assert "key_files" in proposals[0].proposed_location

    def test_deduplicate_proposals(self, duplicate_proposals):
        """Duplicate proposals removed"""
        engine = EnhancementEngine()
        deduped = engine.deduplicate_proposals(duplicate_proposals)
        assert len(deduped) < len(duplicate_proposals)

    def test_apply_proposals(self, temp_profile, test_proposals):
        """Apply proposals updates profile"""
        applier = ProposalApplier()
        result = applier.apply_proposals("test-agent", test_proposals, [0, 1])
        assert result.success
        assert result.applied_count == 2
        # Verify profile was updated
        updated = ProfileManager().load("test-agent")
        assert updated.version > temp_profile.version
```

### 2.4 Agent Lifecycle Tests

```python
class TestAgentManager:
    """Test agent spawning and management."""

    def test_spawn_headless_agent(self, mock_project_path):
        """Spawn headless agent successfully"""
        mgr = AgentManager()
        agent = mgr.spawn("test-agent", mock_project_path, mode="headless")
        assert agent.pid is not None
        assert agent.state == AgentState.RUNNING
        mgr.kill("test-agent")

    def test_spawn_persistent_agent(self, mock_project_path):
        """Spawn persistent agent (tmux session)"""
        mgr = AgentManager()
        agent = mgr.spawn("test-agent", mock_project_path, mode="persistent")
        assert agent.tmux_session is not None
        assert agent.state == AgentState.RUNNING
        mgr.kill("test-agent")

    def test_spawn_nonexistent_project(self):
        """Spawn fails for nonexistent project"""
        mgr = AgentManager()
        with pytest.raises(ProjectNotFound):
            mgr.spawn("test-agent", "/nonexistent/path")

    def test_send_task_success(self, mock_agent):
        """Task execution succeeds"""
        mgr = AgentManager()
        result = mgr.send_task("test-agent", "Test task", timeout=10)
        assert result.status == "success"
        assert len(result.output) > 0

    def test_send_task_timeout(self, mock_agent):
        """Task times out"""
        mgr = AgentManager()
        result = mgr.send_task("test-agent", "Hang task", timeout=1)
        assert result.status == "timeout"
        assert result.duration_seconds >= 1

    def test_kill_graceful(self, mock_agent):
        """Kill agent gracefully"""
        mgr = AgentManager()
        mgr.kill("test-agent", graceful=True)
        # Process should be dead after timeout
        assert not mgr.monitor("test-agent").alive

    def test_health_check(self, mock_agent):
        """Health check works"""
        mgr = AgentManager()
        status = mgr.monitor("test-agent")
        assert status.alive
        assert status.responsive
```

---

## 3. Integration Tests

### 3.1 End-to-End Workflows

```python
class TestProfileToClaudeMd:
    """Test profile → CLAUDE.md generation pipeline."""

    def test_full_pipeline(self, mock_project_path):
        """Create profile → generate CLAUDE.md → verify content"""
        pm = ProfileManager()
        profile = pm.create("e2e-test", mock_project_path)
        pm.save(profile)

        gen = ClaudeMdGenerator()
        gen.generate_all("e2e-test")

        # Verify files exist
        assert os.path.exists(f"{mock_project_path}/CLAUDE.md")

        # Verify content
        with open(f"{mock_project_path}/CLAUDE.md") as f:
            content = f.read()
            assert "e2e-test" in content
            assert profile.identity.display_name in content

class TestSignalToEnhancement:
    """Test signal → proposal → applied enhancement."""

    def test_full_cycle(self, temp_agent_setup):
        """Accumulate signals → generate proposals → apply → verify profile"""
        # Log 5 signals
        acc = EnhancementAccumulator()
        for i in range(5):
            signal = Signal(
                type=SignalType.USER_CORRECTED,
                task_id=f"task_{i:03d}",
                content="User corrected validation"
            )
            acc.log_signal("test-agent", signal)

        # Check threshold hit
        thresholds = acc.check_thresholds("test-agent")
        assert SignalType.USER_CORRECTED in thresholds

        # Generate proposals
        engine = EnhancementEngine()
        proposals = engine.generate_proposals("test-agent")
        assert len(proposals) > 0

        # Apply proposals
        applier = ProposalApplier()
        result = applier.apply_proposals("test-agent", proposals, [0])
        assert result.success

        # Verify profile updated
        pm = ProfileManager()
        profile = pm.load("test-agent")
        assert len(profile.rules.soft) > 0

class TestTaskExecution:
    """Test task → agent → signals → results."""

    def test_task_produces_signals(self, mock_agent):
        """Executing task produces enhancement signals"""
        mgr = AgentManager()
        result = mgr.send_task("test-agent", "Fix auth bug")
        assert result.status == "success"
        assert len(result.signals) > 0
        # Verify signals are saved
        acc = EnhancementAccumulator()
        for signal in result.signals:
            acc.log_signal("test-agent", signal)
        loaded = acc.load_accumulator("test-agent")
        assert len(loaded.signals) > 0
```

---

## 4. Test Fixtures

### 4.1 Pytest Fixtures

```python
# tests/conftest.py

@pytest.fixture
def temp_agent_dir(tmp_path):
    """Create temporary agent directory"""
    agent_dir = tmp_path / ".claude-bridge" / "agents" / "test-agent"
    agent_dir.mkdir(parents=True)
    yield agent_dir

@pytest.fixture
def mock_profile(temp_agent_dir):
    """Create mock profile"""
    return Profile(
        name="test-agent",
        version=1,
        created=datetime.now(),
        identity=Identity(
            role="coder",
            display_name="Test Coder",
            project="/tmp/test-project",
            description="Test agent"
        ),
        rules=Rules(hard=[], soft=[])
    )

@pytest.fixture
def mock_project_path(tmp_path):
    """Create mock project directory"""
    project = tmp_path / "test-project"
    project.mkdir()
    (project / "package.json").write_text(json.dumps({
        "name": "test-app",
        "dependencies": {"nextjs": "^15"}
    }))
    (project / "README.md").write_text("# Test Project")
    return str(project)

@pytest.fixture
def mock_agent(mock_project_path):
    """Create and start mock agent"""
    mgr = AgentManager()
    agent = mgr.spawn("test-agent", mock_project_path)
    yield agent
    mgr.kill("test-agent")
```

---

## 5. Coverage Goals

### 5.1 Coverage Targets

- **Unit tests:** 85%+ code coverage
- **Integration tests:** All major workflows tested
- **Critical paths:** 100% coverage (profile, permission, agent lifecycle)

### 5.2 Coverage Command

```bash
pytest --cov=claude_bridge --cov-report=html tests/
```

---

## 6. CI/CD Integration

### 6.1 GitHub Actions Workflow

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -e ".[dev]"
      - run: pytest tests/ --cov=claude_bridge --cov-report=xml
      - uses: codecov/codecov-action@v3
```

---

## 7. Success Criteria

Testing complete when:

- [x] Unit tests written for all components
- [x] Integration tests for major workflows
- [x] Fixtures for common test scenarios
- [x] 85%+ code coverage achieved
- [x] All tests passing
- [x] CI/CD integration working
- [x] Test documentation complete

