from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..services.mobile_receiver import receiver

router = APIRouter(prefix="/api/mobile", tags=["mobile"])


@router.post("/session")
def start_session():
    try:
        return receiver.start()
    except Exception as exc:  # noqa: BLE001 - surface setup failures to the UI
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/session")
def session_status():
    return receiver.status()


@router.delete("/session")
def stop_session():
    receiver.stop()
    return {"ok": True}
