"""API метаданных плагинов и создания пользовательских компонентов."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError

from backend.core.plugin_catalog import (
    UpdateCustomPluginPayload,
    delete_custom_plugin,
    get_plugin_detail,
    read_plugin_template_code,
    update_custom_plugin,
)
from backend.core.plugin_manager import get_plugin_manager
from backend.core.plugins import CreateCustomPluginPayload, create_custom_plugin

router = APIRouter(tags=["plugins"])


@router.get("/api/plugins")
def list_plugins():
    manager = get_plugin_manager()
    return {"plugins": manager.get_public_metadata()}


@router.get("/api/plugins/{plugin_id}")
def get_plugin(plugin_id: str):
    try:
        return get_plugin_detail(plugin_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/plugins/{plugin_id}/code")
def get_plugin_code(plugin_id: str):
    try:
        template_code = read_plugin_template_code(plugin_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return PlainTextResponse(template_code or "", media_type="text/plain; charset=utf-8")


@router.put("/api/plugins/{plugin_id}")
def update_plugin(plugin_id: str, payload: UpdateCustomPluginPayload):
    try:
        result = update_custom_plugin(plugin_id, payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Не удалось записать файлы плагина: {exc}") from exc

    manager = get_plugin_manager()
    return {
        **result,
        "plugins": manager.get_public_metadata(),
        "count": len(manager.list_plugins()),
    }


@router.delete("/api/plugins/{plugin_id}")
def remove_plugin(plugin_id: str):
    try:
        result = delete_custom_plugin(plugin_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    manager = get_plugin_manager()
    return {
        **result,
        "plugins": manager.get_public_metadata(),
        "count": len(manager.list_plugins()),
    }


@router.post("/api/plugins/reload")
def reload_plugins():
    manager = get_plugin_manager()
    manager.reload()
    return {"plugins": manager.get_public_metadata(), "count": len(manager.list_plugins())}


@router.post("/api/plugins/create-custom")
def create_custom_plugin_endpoint(payload: CreateCustomPluginPayload):
    try:
        result = create_custom_plugin(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Не удалось записать файлы плагина: {exc}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    manager = get_plugin_manager()
    return {
        **result,
        "plugins": manager.get_public_metadata(),
        "count": len(manager.list_plugins()),
    }
