from typing import Dict

from src.models.valves import OVValveBehaviorConfig


def update_ov_state(state: Dict, behavior: OVValveBehaviorConfig, open_signal: bool, close_signal: bool, now: float) -> Dict:
    previous_open = bool(state.get("open_detector_last", False))
    previous_close = bool(state.get("close_detector_last", False))
    open_rising_edge = bool(open_signal) and not previous_open
    close_rising_edge = bool(close_signal) and not previous_close

    state["open_detector_last"] = bool(open_signal)
    state["close_detector_last"] = bool(close_signal)
    state["detector_open_active"] = bool(open_signal)
    state["detector_close_active"] = bool(close_signal)
    state["input_high"] = bool(open_signal)

    # Only seed the default position on a true cold start. During a commanded
    # transition `position` is intentionally None until the detector_delay
    # timer fires; reseeding it here would briefly flip the matching feedback
    # relay back on mid-travel.
    if state.get("position") is None and not state.get("pending_action"):
        state["position"] = behavior.default_position

    if open_rising_edge:
        if state.get("position") == "open" and not state.get("pending_action"):
            # Already parked at the open limit. Hold the existing feedback so
            # the controller's confirm-open channel reads ~5V on its first
            # poll instead of dropping to 0V for the detector_delay window.
            state["open_feedback_until"] = max(
                float(state.get("open_feedback_until", 0.0) or 0.0),
                now + behavior.feedback_hold_seconds,
            )
        else:
            state["pending_action"] = "open"
            state["action_due_at"] = now + behavior.detector_delay_seconds
            state["mode"] = "WAIT_OPEN"
            state["position"] = None
            # Cancel any stale opposite-direction hold so it can't briefly
            # re-energize the wrong feedback relay during this transition.
            state["close_feedback_until"] = 0.0

    if close_rising_edge:
        if state.get("position") == "closed" and not state.get("pending_action"):
            state["close_feedback_until"] = max(
                float(state.get("close_feedback_until", 0.0) or 0.0),
                now + behavior.feedback_hold_seconds,
            )
        else:
            state["pending_action"] = "close"
            state["action_due_at"] = now + behavior.detector_delay_seconds
            state["mode"] = "WAIT_CLOSE"
            state["position"] = None
            state["open_feedback_until"] = 0.0

    pending_action = state.get("pending_action")
    action_due_at = float(state.get("action_due_at", 0.0) or 0.0)
    if pending_action and now >= action_due_at:
        if pending_action == "open":
            state["open_feedback_until"] = now + behavior.feedback_hold_seconds
            state["position"] = "open"
            state["mode"] = "OPEN_FEEDBACK"
        else:
            state["close_feedback_until"] = now + behavior.feedback_hold_seconds
            state["position"] = "closed"
            state["mode"] = "CLOSE_FEEDBACK"
        state["pending_action"] = None
        state["action_due_at"] = 0.0

    open_hold_active = now < float(state.get("open_feedback_until", 0.0) or 0.0)
    close_hold_active = now < float(state.get("close_feedback_until", 0.0) or 0.0)

    position = state.get("position")
    state["feedback_open_active"] = open_hold_active or position == "open"
    state["feedback_close_active"] = close_hold_active or position == "closed"

    if state["pending_action"] == "open":
        state["mode"] = "WAIT_OPEN"
    elif state["pending_action"] == "close":
        state["mode"] = "WAIT_CLOSE"
    elif open_hold_active:
        state["mode"] = "OPEN_FEEDBACK"
    elif close_hold_active:
        state["mode"] = "CLOSE_FEEDBACK"
    elif position == "open":
        state["mode"] = "OPEN"
    elif position == "closed":
        state["mode"] = "CLOSED"
    else:
        state["mode"] = "UNKNOWN"

    return state
