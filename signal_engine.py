from dataclasses import dataclass
from typing import Optional


@dataclass
class SignalState:
    stage: str = "WAIT_SWEEP"
    direction: Optional[str] = None
    sweep: Optional[dict] = None
    choch: Optional[dict] = None
    bos: Optional[dict] = None

    def reset(self):
        self.stage = "WAIT_SWEEP"
        self.direction = None
        self.sweep = None
        self.choch = None
        self.bos = None

    def register_sweep(self, sweep):
        self.sweep = sweep
        self.direction = sweep["direction"]
        self.stage = "WAIT_CHOCH"

    def register_choch(self, choch):
        if self.sweep is None:
            return False

        if choch["time"] <= self.sweep["time"]:
            return False

        if choch["direction"] != self.direction:
            return False

        self.choch = choch
        self.stage = "WAIT_BOS"
        return True

    def register_bos(self, bos):
        if self.choch is None:
            return False

        if bos["time"] <= self.choch["time"]:
            return False

        if bos["direction"] != self.direction:
            return False

        self.bos = bos
        self.stage = "READY_FOR_ENTRY"
        return True

    def is_ready(self):
        return self.stage == "READY_FOR_ENTRY"