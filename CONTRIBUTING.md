# Contributing to Document Intelligence Pipeline

Thank you for your interest in contributing to the **Document Intelligence Pipeline**! We welcome bug fixes, documentation improvements, new sample invoice fixtures, and feature contributions.

---

## 🛠️ Development Setup

### 1. Clone & Set Up Python Environment
```bash
git clone https://github.com/DOWNEY7/document-intelligence-pipeline.git
cd document-intelligence-pipeline

python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 2. Code Quality & Standards
We use **Ruff** for linting and code formatting, and **Pytest** for testing.

- **Format & Lint**:
  ```bash
  ruff check src/ tests/ --fix
  ruff format src/ tests/
  ```

- **Run Full Test Suite**:
  ```bash
  pytest
  ```

- **Run Coverage**:
  ```bash
  pytest --cov=src --cov-report=term-missing
  ```

---

## 🔄 Pull Request Workflow

1. Fork the repository and create a descriptive feature branch:
   ```bash
   git checkout -b feat/your-feature-name
   ```
2. Write clean, modular code with accompanying docstrings and Pydantic v2 schemas where appropriate.
3. Add corresponding unit and integration test coverage under `tests/`.
4. Ensure all tests pass locally (`pytest`) and linters report 0 errors (`ruff check src/ tests/`).
5. Open a Pull Request referencing any related issues.

---

## 📐 Architecture Principles
- **Dual-Storage Contract**: Any change to normalized models must maintain backwards-compatibility with the immutable raw extraction audit storage.
- **Offline First**: All services must function in 100% offline mock mode when Azure credentials are not present.
