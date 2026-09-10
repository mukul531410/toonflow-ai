# Blender Runtime Verification

## Overview
This document describes the runtime verification mechanisms implemented for the TOONFLOW AI Blender add-on. It ensures that Blender operators execute correctly, produce expected results, and maintain registration state integrity during automated testing and production use.

## Functional Runtime Validation
The verification system validates that Blender operators:
- Execute successfully (return `FINISHED` status)
- Produce correct output data (e.g., scene generation results)
- Update internal state (`last_status`) appropriately
- Maintain registration state consistency after execution, even when errors occur

## Pipeline Stub
A lightweight pipeline stub (`pipeline.api`) is used to intercept Blender operator calls during verification:

- **Import**: The stub imports `pipeline.api` and provides `SceneCreationResult` and `GenerationResult` types.
- **Injection**: Before importing `toonflow_ai`, the stub is injected to monitor operator execution.
- **Result Handling**: After operator execution, the stub checks the returned status and result data, ensuring correctness before proceeding.

## Verification Process
1. **Preparation**: The pipeline stub is applied to the Python environment before importing `toonflow_ai`.
2. **Execution**: The script invokes `bpy.ops.toonflow.generate_scene()` for each test case.
3. **Validation**: The system checks:
   - Operator return value (`FINISHED`, `CANCELLED`, etc.)
   - `last_status` field updates correctly
   - Registration state integrity (no duplicate registrations, proper cleanup)
4. **Error Handling**: The verification script handles both expected errors (e.g., known error codes) and unexpected exceptions, ensuring graceful recovery.

## Test Integration
The verification logic is integrated into the existing test suite via the `verify_blender_functional_runtime` function in `workflow/verification.py`. This function:
- Executes the runtime validation script
- Asserts expected outcomes for each test scenario (empty concept, valid concept, known error, unexpected error)
- Provides detailed error messages for failed validations

## Reference Implementation
Key files involved:
- `workflow/runtime.py`: Contains `_BLENDER_FUNCTIONAL_RUNTIME_SCRIPT` with actual operator calls.
- `workflow/verification.py`: Contains `verify_blender_functional_runtime` and supporting utilities.
- `tests/test_verification.py`: Test cases that invoke the verification logic.

## Usage
To run functional runtime verification locally:
```bash
python -m unittest discover -s tests -p "*verification*"
```
Ensure Blender is available in the environment and the `toonflow_ai` add-on is installed.