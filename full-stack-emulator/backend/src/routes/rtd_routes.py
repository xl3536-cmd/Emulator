from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel

from src.controllers.rtd_controller import rtd_controller


class RtdCsvPayload(BaseModel):
    header: List[str]
    rows: List[Dict[str, Any]]
    filename: str | None = None


class PlaybackPayload(BaseModel):
    playing: bool


class BoardBitsPayload(BaseModel):
    bits: List[int]


router = APIRouter(prefix="/api/runtime/rtd", tags=["RTD"])


@router.post("/csv")
def load_rtd_csv(payload: RtdCsvPayload):
    return rtd_controller.load_csv(payload.header, payload.rows, payload.filename)


@router.post("/csv/clear")
def clear_rtd_csv():
    return rtd_controller.clear_csv()


@router.post("/playback")
def set_rtd_playback(payload: PlaybackPayload):
    return rtd_controller.set_playback(payload.playing)


@router.post("/boards/{board_index}")
def set_rtd_board_bits(board_index: int, payload: BoardBitsPayload):
    return rtd_controller.set_board_bits(board_index, payload.bits)
