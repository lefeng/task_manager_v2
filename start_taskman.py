#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Entry point for the frozen taskman binary.

In development, use: python main.py (uvicorn reload mode)
In production / frozen binary, use this file (app object passed directly).
"""

import uvicorn
from main import app
from core.config import settings

if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port)
