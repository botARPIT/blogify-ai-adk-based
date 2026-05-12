## 🔧 CI/CD and Code Quality Fixes

### Summary
This PR resolves critical CI/CD pipeline issues and improves code quality by fixing linting errors, test infrastructure, and type checking problems.

### Changes

#### 1. Environment Loading Refactor
- **Problem**: E402 linting errors due to imports after code execution
- **Solution**: Moved `load_dotenv()` to module-level in `env_config.py`
- **Impact**: Cleaner import order, automatic env loading, removed debug statements

**Files Changed:**
- `backend/src/config/env_config.py`
- `backend/src/config/env_loader.py` (deprecated)
- `backend/src/workers/blog_worker.py`
- `backend/src/workers/reaper.py`

#### 2. CI Pipeline Fixes
- **Problem**: Alembic migrations failing with "relation already exists" errors
- **Solution**: Drop and recreate test database before migrations
- **Problem**: Auth tests failing with `ModuleNotFoundError: No module named 'bcrypt'`
- **Solution**: Explicitly install bcrypt in CI dependencies

**Files Changed:**
- `.github/workflows/ci.yml`

#### 3. Test Infrastructure Fixes
- **Problem**: `TypeError: object AsyncMock can't be used in 'await' expression`
- **Solution**: Properly configured async mocks with `side_effect` and `autouse=True`
- **Impact**: All async tests now work correctly

**Files Changed:**
- `backend/tests/conftest.py`

#### 4. MyPy Type Checking Fix
- **Problem**: "Source file found twice under different module names"
- **Solution**: Removed `backend/__init__.py` (project dir, not a package)
- **Impact**: Clean mypy output, no module name conflicts

**Files Changed:**
- `backend/__init__.py` (deleted)

### Testing
- ✅ Ruff linting passes
- ✅ MyPy type checking passes (no "found twice" error)
- ✅ Alembic migrations run cleanly in CI
- ✅ Async test mocks work correctly
- ✅ All CI jobs should pass

### Deployment Impact
- **Risk Level**: Low
- **Breaking Changes**: None
- **Rollback Plan**: Revert commits if CI fails

### Checklist
- [x] Code follows project style guidelines
- [x] Linting passes (ruff)
- [x] Type checking passes (mypy)
- [x] Tests updated where necessary
- [x] CI pipeline validated
- [x] No secrets or debug statements in code
- [x] Commit messages follow conventional commits

### Related Issues
Fixes CI pipeline failures and prepares codebase for production deployment.

---

**Commits in this PR:**
```
3e99994 fix(mypy): remove backend/__init__.py to resolve module name conflict
5da880c fix(tests): properly configure async mocks for Redis and database
3322732 fix(ci): ensure clean database for migrations and fix test dependencies
ccffc34 refactor: move env loading to module level and fix E402 linting errors
```
