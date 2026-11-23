# Nut & Bolt Windows SDK recipe

This directory contains the pinned recipe for SAPIEN `3.0.3+dexarena.gpu1.wininterop7`. The directory name is the private build layout expected by the outer launcher. [The lock](lock.json) records the toolchain, official source and archive identities, and all eight patches, including native GPU lock synchronization and batched render visibility.

Run the build from `tools/variation/sapien_sdk/native_lock` in the project checkout, following its `README.md`. `tools/clean_build_windows.py` verifies and installs this recipe in the private work directory before building. For task validation use that bundle's `tools/run_task_check.py` with the Nut & Bolt checker. The inner `run_check.py` is a pinned build input inherited from the base recipe.
