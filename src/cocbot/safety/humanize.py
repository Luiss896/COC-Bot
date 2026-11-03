"""Humanization e controlli anti-ban.

**Onestà (importante):** queste misure rendono il comportamento *meno regolare* e riducono
alcuni segnali semplici (ritmi perfetti, sessioni continue senza pause, azioni ripetute sullo
stesso punto), ma **non garantiscono** l'immunità dal ban: Supercell può rilevare l'automazione
anche con analisi lato server, pattern di input o segnalazioni. L'unica protezione reale resta
non automatizzare o usare un account dedicato.

Cosa facciamo concretamente:
- ritardi tra azioni con distribuzione non uniforme (più corti frequenti, ogni tanto più lunghi);
- pause casuali brevi ("distrazione") e pause lunghe periodiche;
- tap occasionali su erba vuota (mai su gemme/shop/pulsanti) quando la schermata è home;
- limiti di rate (azioni/minuto) e rilevazione di pattern ripetitivi (stesso punto, nessuna pausa);
- report di rischio consultabile dalla GUI.
"""
from __future__ import annotations

import random
import time
from collections import Counter, deque
from dataclasses import dataclass

from cocbot.config.models import HumanizeConfig
from cocbot.core.types import GamePoint


class Humanizer:
    """Genera tempi/pause "umane" a partire dalla configurazione."""

    def __init__(self, config: HumanizeConfig | None = None, *, rng: random.Random | None = None) -> None:
        self.config = config or HumanizeConfig()
        self.rng = rng or random.Random()
        self._last_long_break_min: float = 0.0
        self._breaks_taken: int = 0

    @property
    def breaks_taken(self) -> int:
        return self._breaks_taken

    def next_action_delay_s(self) -> float:
        """Ritardo prima della prossima azione, sbilanciato verso il basso (umano)."""
        lo, hi = self.config.action_delay_ms
        if not self.config.enabled or hi <= 0:
            return max(0.0, lo / 1000.0)
        # random()**1.7 concentra i valori vicino al minimo, con coda verso il massimo
        value = lo + (hi - lo) * (self.rng.random() ** 1.7)
        return max(self.config.min_seconds_between_actions, value / 1000.0)

    def maybe_break_s(self) -> float:
        """Pausa breve casuale (0 se non capita)."""
        if not self.config.enabled or self.rng.random() >= self.config.break_probability:
            return 0.0
        lo, hi = self.config.break_duration_s
        duration = self.rng.uniform(lo, hi)
        self._breaks_taken += 1
        return duration

    def maybe_idle_tap(self) -> bool:
        if not self.config.enabled:
            return False
        return self.rng.random() < self.config.idle_tap_probability

    def long_break_due(self, session_minutes: float) -> float:
        """Pausa lunga periodica: ritorna 0 se non è ancora il momento."""
        if not self.config.enabled or self.config.long_break_every_min <= 0:
            return 0.0
        period = float(self.config.long_break_every_min)
        due_at = self._last_long_break_min + period
        if session_minutes < due_at:
            return 0.0
        lo, hi = self.config.long_break_duration_s
        self._last_long_break_min = session_minutes
        self._breaks_taken += 1
        return self.rng.uniform(lo, hi)

    def think_time_s(self) -> float:
        """Micro-pausa di "riflessione" prima di un'azione importante."""
        return self.rng.uniform(0.15, 0.9) if self.config.enabled else 0.0


@dataclass(frozen=True)
class AntiBanSnapshot:
    session_s: float
    actions: int
    actions_per_min: float
    unique_targets: int
    max_same_target_streak: int
    breaks: int
    warnings: tuple[str, ...]


class AntiBanMonitor:
    """Tiene traccia del comportamento e segnala pattern a rischio ban."""

    def __init__(
        self,
        config: HumanizeConfig | None = None,
        *,
        clock=time.monotonic,
    ) -> None:
        self.config = config or HumanizeConfig()
        self.clock = clock
        self._start = clock()
        self._action_times: deque[float] = deque(maxlen=240)
        self._targets: Counter[tuple[int, int]] = Counter()
        self._last_target: tuple[int, int] | None = None
        self._same_streak = 0
        self._max_same_streak = 0
        self._actions = 0
        self._breaks = 0

    @property
    def actions(self) -> int:
        return self._actions

    @property
    def breaks(self) -> int:
        return self._breaks

    def record_action(self, point: GamePoint | None = None) -> None:
        now = self.clock()
        self._action_times.append(now)
        self._actions += 1
        if point is not None:
            key = (int(point.x), int(point.y))
            self._targets[key] += 1
            if key == self._last_target:
                self._same_streak += 1
            else:
                self._same_streak = 1
                self._last_target = key
            self._max_same_streak = max(self._max_same_streak, self._same_streak)
        else:
            self._same_streak = 0

    def record_break(self, duration_s: float) -> None:
        if duration_s > 0:
            self._breaks += 1

    def session_seconds(self) -> float:
        return self.clock() - self._start

    def actions_per_minute(self) -> float:
        now = self.clock()
        recent = [t for t in self._action_times if now - t <= 60.0]
        return float(len(recent))

    def next_delay_s(self) -> float:
        """Attesa necessaria per rispettare il rate massimo di azioni/minuto."""
        if not self.config.enabled:
            return 0.0
        now = self.clock()
        recent = [t for t in self._action_times if now - t <= 60.0]
        limit = self.config.max_actions_per_minute
        if len(recent) < limit:
            return 0.0
        oldest = recent[-limit]
        return max(0.0, 60.0 - (now - oldest) + 0.05)

    def warnings(self) -> list[str]:
        out: list[str] = []
        apm = self.actions_per_minute()
        if self.config.enabled and apm >= self.config.max_actions_per_minute * 0.9:
            out.append(f"ritmo alto: {apm:.0f} azioni/min (limite {self.config.max_actions_per_minute})")
        if self._max_same_streak >= self.config.max_same_target_repeats:
            out.append(f"stesso punto ripetuto {self._max_same_streak} volte di fila")
        if len(self._targets) >= 4:
            common_count = self._targets.most_common(1)[0][1]
            total = sum(self._targets.values())
            if total >= 10 and common_count / total > 0.7:
                out.append("poca varietà di punti cliccati (70%+ sullo stesso punto)")
        session_min = self.session_seconds() / 60.0
        if (
            self.config.enabled
            and self.config.long_break_every_min > 0
            and session_min > self.config.long_break_every_min * 2
            and self._breaks == 0
        ):
            out.append("sessione lunga senza pause")
        return out

    def snapshot(self) -> AntiBanSnapshot:
        return AntiBanSnapshot(
            session_s=round(self.session_seconds(), 1),
            actions=self._actions,
            actions_per_min=round(self.actions_per_minute(), 1),
            unique_targets=len(self._targets),
            max_same_target_streak=self._max_same_streak,
            breaks=self._breaks,
            warnings=tuple(self.warnings()),
        )
