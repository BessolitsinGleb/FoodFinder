"""Точка входа.
Запуск из папки backend:
    uvicorn main:app --reload
или
    python main.py
"""
import uvicorn
from app.application import create_app
from app.core.config import get_settings

app = create_app()

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.app.host,
        port=settings.app.port,
        reload=settings.app.env == "local",
    )
