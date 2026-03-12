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
    "core/pg_listener.py",
    "grpc_gen/job_runner_pb2.py",
    "grpc_gen/job_runner_pb2_grpc.py",
    "jobs/events.py",
    "jobs/models.py",
    "jobs/router.py",
    "jobs/schemas.py",
    "jobs/service.py",
    "jobs/ws_manager.py",
]


def clean_files(file_types="all", description="files"):
    """Remove compiled files based on type

    Args:
        file_types: "all", "compiled", "intermediate", or list of extensions
        description: Description for logging
    """
    print(f"🧹 Cleaning up {description}...")

    # Define file type groups
    type_groups = {
        "compiled": ["*.so", "*.pyd", "*.dll"],
        "intermediate": ["*.c", "*.cpp"],
        "all": ["*.so", "*.pyd", "*.dll", "*.c", "*.cpp"],
    }

    # Determine which extensions to remove
    if isinstance(file_types, str):
        extensions_to_remove = type_groups.get(file_types, [])
    else:
        extensions_to_remove = file_types

    if not extensions_to_remove:
        print(f"  No file types specified for {description}")
        return 0

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

    print(f"✅ Removed {removed_count} {description}")
    return removed_count


def check_dependencies():
    """Check if required dependencies are installed"""
    try:
        import Cython

        print(f"✅ Cython version: {Cython.__version__}")
    except ImportError:
        print("❌ Cython not installed. Install with: pip install Cython")
        return False

    try:
        import cx_Freeze

        print(f"✅ cx_Freeze version: {cx_Freeze.__version__}")
    except ImportError:
        print("❌ cx_Freeze not installed. Install with: pip install cx_Freeze")
        return False

    return True


def compile_module(module_path):
    """Compile a single module with Cython"""
    if not os.path.exists(module_path):
        print(f"Warning: {module_path} not found, skipping")
        return False

    print(f"Compiling {module_path}...")

    try:
        # Use an inline setup script with explicit packages=[] to avoid
        # setuptools' multi-package auto-discovery error
        inline_script = (
            "import sys; from setuptools import setup; "
            "from Cython.Build import cythonize; "
            f"setup(packages=[], ext_modules=cythonize(['{module_path}'], "
            "language_level=3, force=True), "
            "script_args=['build_ext', '--inplace'])"
        )
        cmd = [sys.executable, "-c", inline_script]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            print(f"✅ Successfully compiled {module_path}")
            return True
        else:
            print(f"❌ Failed to compile {module_path}")
            print(f"Keeping as Python file")
            # Don't print full error to keep output clean
            return False

    except Exception as e:
        print(f"❌ Exception compiling {module_path}: {e}")
        return False


def compile_all_modules():
    """Compile all specified modules"""
    print("\n🔨 Starting Cython compilation...")

    # Check which modules exist
    available_modules = [m for m in cython_modules if os.path.exists(m)]

    if not available_modules:
        print("No modules found to compile")
        return False

    success_count = 0
    for module_path in available_modules:
        if compile_module(module_path):
            success_count += 1

    print(f"\n📊 Compiled {success_count}/{len(available_modules)} modules")

    if success_count > 0:
        print("✅ Some modules compiled successfully!")
        return True
    else:
        print("⚠️  No modules were compiled")
        return False


def check_compilation_results():
    """Show which modules were successfully compiled"""
    print("\n📋 Compilation results:")

    for module_path in cython_modules:
        if not os.path.exists(module_path):
            continue

        module_dir = os.path.dirname(module_path)
        module_name = os.path.basename(module_path).replace(".py", "")

        # Look for compiled extension files
        so_files = []
        for ext in [".so", ".pyd", ".dll"]:
            pattern = os.path.join(module_dir, f"{module_name}*{ext}")
            so_files.extend(glob.glob(pattern))

        if so_files:
            print(f"✅ {module_path} → compiled")
        else:
            print(f"🐍 {module_path} → Python")


def build_with_cx_freeze():
    """Run the cx_Freeze build"""
    print("\n📦 Building with cx_Freeze...")

    try:
        result = subprocess.run(
            [sys.executable, "setup.py", "build"], capture_output=True, text=True
        )

        if result.returncode == 0:
            print("✅ cx_Freeze build successful!")
            return True
        else:
            print("❌ cx_Freeze build failed:")
            print(result.stderr)
            return False

    except Exception as e:
        print(f"❌ Exception during cx_Freeze build: {e}")
        return False


def main():
    """Main build process"""
    print("Taskman - Cython Build")
    print("=" * 50)

    # Parse command line arguments
    compile_only = "--compile-only" in sys.argv
    build_only = "--build-only" in sys.argv
    clean_only = "--clean" in sys.argv

    if clean_only:
        clean_files("all", "all compiled and intermediate files")
        print("✅ Cleanup complete!")
        return

    # Check dependencies
    if not check_dependencies():
        print("\n❌ Missing dependencies. Please install and try again.")
        sys.exit(1)

    try:
        # Always clean first for consistent builds
        clean_files("all", "all compiled and intermediate files")

        if not build_only:
            # Compile with Cython
            compile_success = compile_all_modules()
            check_compilation_results()

            # Clean up intermediate files after successful build
            clean_files("intermediate", "intermediate C/C++ files")

            if compile_only:
                print("\n✅ Compilation complete!")
                return

        if not compile_only:
            # Build with cx_Freeze
            build_success = build_with_cx_freeze()

            if build_success:
                print("\n🎉 Complete build successful!")
                print("📁 Output: build/exe/")
                print("🚀 Test with: ./build/exe/taskman")
                print("\n📋 What's included:")
                print("  ✅ Compiled .so files (performance)")
                print("  ✅ Python .py files (fallback)")
                print("  ❌ Intermediate .c files (cleaned up)")
            else:
                print("\n⚠️  cx_Freeze build failed")
                print(
                    "💡 Try: python3 setup_cython.py --clean && python3 setup.py build"
                )

    except KeyboardInterrupt:
        print("\n\n⚠️  Build interrupted by user")
    except Exception as e:
        print(f"\n❌ Build failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--help":
            print("Usage:")
            print("  python3 setup_cython.py              # Clean + compile + build")
            print("  python3 setup_cython.py --clean      # Just clean compiled files")
            print("  python3 setup_cython.py --compile-only # Just compile with Cython")
            print(
                "  python3 setup_cython.py --build-only   # Just build with cx_Freeze"
            )
            sys.exit(0)

    main()
