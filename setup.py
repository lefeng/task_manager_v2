from cx_Freeze import setup, Executable
import os
import sys

base_dir = os.path.dirname(os.path.abspath(__file__))

include_files = []

build_exe_options = {
    "packages": [
        "uvicorn",
        "fastapi",
        "starlette",
        "sqlalchemy",
        "asyncpg",
        "pydantic",
        "pydantic_core",
        "pydantic_settings",
        "grpc",
        "google.protobuf",
        "anyio",
        "anyio._backends",
        "httptools",
        "uvloop",
        "websockets",
        "h11",
        "blueprints",
        "core",
        "grpc_gen",
        "jobs",
    ],
    "include_files": include_files,
    "excludes": ["tkinter", "test", "distutils"],
    "build_exe": "build/exe",
    "zip_include_packages": "",
    "optimize": 2,
    "include_msvcr": True,
}

executables = [
    Executable(
        script="start_taskman.py",
        base=None,
        target_name="taskman",
    ),
]


def cleanup_build_folder(build_dir):
    """Remove license file, share folder, and create symbolic link to .env"""
    license_file = os.path.join(build_dir, "frozen_application_license.txt")
    if os.path.exists(license_file):
        os.remove(license_file)
        print(f"Removed {license_file}")

    share_dir = os.path.join(build_dir, "share")
    if os.path.exists(share_dir):
        import shutil

        shutil.rmtree(share_dir)
        print(f"Removed {share_dir}")

    env_link = os.path.join(build_dir, ".env")
    if not os.path.exists(env_link):
        os.symlink("../.env", env_link)
        print(f"Created symlink {env_link} -> ../.env")


setup(
    name="Taskman",
    version="2.0.0",
    description="Task Manager",
    options={"build_exe": build_exe_options},
    executables=executables,
)


# Post-build cleanup
cleanup_build_folder(build_exe_options["build_exe"])
