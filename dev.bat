@echo off
start "API Server" powershell -NoExit -Command "uv run --package api-server uvicorn api_server.main:app --reload"
cd services\dashboard && pnpm dev
