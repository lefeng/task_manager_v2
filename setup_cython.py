#!/usr/bin/env python3

import os
import glob
import subprocess
import sys

# Taskman v2 modules to compile with Cython
cython_modules = [
    "main.py",
    "start_taskman.py",
    "blueprints/models.py",
    "blueprints/router.py",
    "blueprints/schemas.py",
    "blueprints/service.py",
    "core/config.py",
    "core/database.py",
    "core/grpc_client.py",
    "grpc_gen/job_runner_pb2.py",
    "grpc_gen/job_runner_pb2_grpc.py",
    "jobs/models.py",
    "jobs/router.py",
    "jobs/schemas.py",
    "jobs/service.py",
    "jobs/ws_manager.py",
]


def clean_files(file_types="all", description="files"):
    print(f"Cleaning up {description}...")

    type_groups = {
        "compiled": ["*.so", "*.pyd", "*.dll"],
        "intermediate": ["*.c", "*.cpp"],
        "all": ["*.so", "*.pyd", "*.dll", "*.c", "*.cpp"],
    }

    if isinstance(file_types, str):
        extensions_to_remove = type_groups.get(file_types, [])
    else:
        extensions_to_remove = file_types

    removed_count = 0

    for root, dirs, files in os.walk("."):
        # Skip venv and build output
        dirs[:] = [d for d in dirs if d not in (".venv", "build", "__pycache__")]
        for ext_pattern in extensions_to_remove:
            for file_path in glob.glob(os.path.join(root, ext_pattern)):
                try:
                    os.remove(file_path)
                    print(f"  Removed: {file_path}")
                    removed_count += 1
                except OSError as e:
                    print(f"  Could not remove {file_path}: {e}")

    print(f"Removed {removed_count} {description}")
    return removed_count


def check_dependencies():
    try:
        import Cython
        print(f"Cython version: {Cython.__version__}")
    except ImportError:
        print("Cython not installed. Install with: pip install Cython")
        return False

    try:
        import cx_Freeze
        print(f"cx_Freeze version: {cx_Freeze.__version__}")
    except ImportError:
        print("cx_Freeze not installed. Install with: pip install cx_Freeze")
        return False

    return True


def compile_module(module_path):
    if not os.path.exists(module_path):
        print(f"Warning: {module_path} not found, skipping")
        return False

    print(f"Compiling {module_path}...")

    try:
        cmd = [
            sys.executable,
            "-m",
            "Cython.Build.Cythonize",
            "-i",       # Build in-place
            "-3",       # Python 3 mode
            "--force",  # Force recompilation
            module_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            print(f"  OK: {module_path}")
            return True
        else:
            print(f"  Failed: {module_path} (keeping as Python file)")
            return False

    except Exception as e:
        print(f"  Exception: {module_path}: {e}")
        return False


def compile_all_modules():
    print("\nStarting Cython compilation...")

    available_modules = [m for m in cython_modules if os.path.exists(m)]

    if not available_modules:
        print("No modules found to compile")
        return False

    success_count = 0
    for module_path in available_modules:
        if compile_module(module_path):
            success_count += 1

    print(f"\nCompiled {success_count}/{len(available_modules)} modules")
    return success_count > 0


def check_compilation_results():
    print("\nCompilation results:")

    for module_path in cython_modules:
        if not os.path.exists(module_path):
            continue

        module_dir = os.path.dirname(module_path) or "."
        module_name = os.path.basename(module_path).replace(".py", "")

        so_files = []
        for ext in [".so", ".pyd", ".dll"]:
            pattern = os.path.join(module_dir, f"{module_name}*{ext}")
            so_files.extend(glob.glob(pattern))

        if so_files:
            print(f"  compiled: {module_path}")
        else:
            print(f"  python:   {module_path}")


def build_with_cx_freeze():
    print("\nBuilding with cx_Freeze...")

    try:
        result = subprocess.run(
            [sys.executable, "setup.py", "build"], capture_output=True, text=True
        )

        if result.returncode == 0:
            print("cx_Freeze build successful!")
            return True
        else:
            print("cx_Freeze build failed:")
            print(result.stderr)
            return False

    except Exception as e:
        print(f"Exception during cx_Freeze build: {e}")
        return False


def main():
    print("TaskManager v2 - Cython Build")
    print("=" * 50)

    compile_only = "--compile-only" in sys.argv
    build_only = "--build-only" in sys.argv
    clean_only = "--clean" in sys.argv

    if clean_only:
        clean_files("all", "all compiled and intermediate files")
        print("Cleanup complete!")
        return

    if not check_dependencies():
        print("\nMissing dependencies. Please install and try again.")
        sys.exit(1)

    try:
        clean_files("all", "all compiled and intermediate files")

        if not build_only:
            compile_all_modules()
            check_compilation_results()
            clean_files("intermediate", "intermediate C/C++ files")

            if compile_only:
                print("\nCompilation complete!")
                return

        if not compile_only:
            build_success = build_with_cx_freeze()

            if build_success:
                print("\nBuild complete!")
                print("Output: build/exe/")
                print("Run:    ./build/exe/taskman")
                print("DB:     ./build/exe/taskman_setup_db [--drop]")
                print("Seed:   ./build/exe/taskman_seed_blueprints --json data/x29/blueprints.json")
            else:
                print("\ncx_Freeze build failed")

    except KeyboardInterrupt:
        print("\nBuild interrupted by user")
    except Exception as e:
        print(f"\nBuild failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    if "--help" in sys.argv:
        print("Usage:")
        print("  python3 setup_cython.py                  # Clean + compile + build")
        print("  python3 setup_cython.py --clean          # Just clean compiled files")
        print("  python3 setup_cython.py --compile-only   # Just compile with Cython")
        print("  python3 setup_cython.py --build-only     # Just build with cx_Freeze")
        sys.exit(0)

    main()
