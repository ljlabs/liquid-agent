# The Way We Work: Code Philosophy

This document defines the architectural principles, development standards, and testing philosophy for the Model Containment project.

## 1. Architectural Blueprint: Thick Server, Thin Client
We adhere to a strict separation of concerns between the backend and the frontend.

### The Python Service (The Brain)
- **Source of Truth**: All business logic, state management, and decision-making reside exclusively in the Python service.
- **State Control**: The backend manages all session state and tool configurations.
- **Data Delivery**: The backend communicates state to the UI via a structured `ViewData` object delivered over an SSE event stream.

### The Web UI (The Renderer)
- **Dumb Client**: The frontend is a pure rendering layer. It is "thin" and "dumb."
- **No Independent State**: The UI does not maintain its own business state or make logical decisions. It reflects the state provided in the most recent `ViewData` snapshot.
- **Stateless Rendering**: If a feature requires a state change, the UI sends an action to the backend and waits for the updated `ViewData` to arrive via the stream to update the display.

---

## 2. Testing Strategy
We utilize a tiered testing approach to ensure stability without sacrificing development speed.

### Unit Tests (The Foundation)
- **Dependency-Free**: Unit tests must have **zero** dependencies. They must not call real LLM APIs, databases, or external tools.
- **Isolation**: Every external interaction must be mocked.
- **Component Focus**: Unit tests target the smallest possible components (e.g., a single function in `view_data.py` or a specific logic branch in `sessions.py`).
- **Coverage Goal**: We strive for **95% test coverage** across all business logic.

### Integration Tests (The Glue)
- **Full Flow**: Integration tests are designed to verify the "golden path" and critical edge cases.
- **End-to-End**: They test the full flow from API request $\rightarrow$ Session Logic $\rightarrow$ Tool Execution $\rightarrow$ ViewData response.
- **Mocked Infrastructure**: They may use mock LLM servers or test databases to ensure reliability and speed.

### Feature-Driven Testing
Every new feature must be accompanied by:
1. A set of **unit tests** covering all underlying logic and edge cases.
2. An **integration test** verifying the feature works as expected in the full system flow.

---

## 3. Documentation & Design Ecosystem
We maintain a living map of the system's design and testing state.

### Design & Specification
- **Feature Specifications**: [[expected_features]] - The source of truth for intended UI/API behavior.
- **Feature Walkthrough**: [[feature_walkthrough]] - A comprehensive guide to implemented features.

### Testing & Coverage
- **Test-to-Feature Mapping**: [[test_feature_mapping]] - Tracks which tests cover which features.
- **Dependency Report**: [[test_dependency_report]] - Analyzes the impact of changes on the test suite.
- **Expansion Plan**: [[planned_unit_test_expansion]] - The roadmap for increasing test coverage.

---

## 4. Development Workflow
1. **Specify**: Define the feature in `expected_features.md`.
2. **Plan**: Draft the implementation and test strategy in a plan file.
3. **Implement**: Write the code and the accompanying unit tests.
4. **Verify**: Run unit tests $\rightarrow$ Run integration tests $\rightarrow$ Manual UI verification.
5. **Synchronize**: Update the `feature_walkthrough.md` and `test_feature_mapping.md` to reflect the changes.
