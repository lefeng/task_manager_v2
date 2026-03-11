from cx_Freeze import setup, Executable
import os
import sys

base_dir = os.path.dirname(os.path.abspath(__file__))

# Bundle the data directory (blueprints seed files)
include_files = [
    ("data", "data"),
]

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
    Executable(
        script="scripts/setup_db.py",
        base=None,
        target_name="taskman_setup_db",
    ),
    Executable(
        script="scripts/seed_blueprints.py",
        base=None,
        target_name="taskman_seed_blueprints",
    ),
]

setup(
    name="TaskManager",
    version="2.0.0",
    description="Task Manager v2",
    options={"build_exe": build_exe_options},
    executables=executables,
)
