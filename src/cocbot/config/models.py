"""Modelli di configurazione (pydantic).

Vincoli non negoziabili:
- ``safety.never_spend_gems`` deve restare True (GemGuard);
- ``safety.ban_iap_shop`` deve restare True;
- la dimensione canonica deve essere 16:9.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class RunMode(StrEnum):
    DRY_RUN = "dry_run"
    SUPERVISED = "supervised"
    AUTONOMOUS = "autonomous"


class WallMode(StrEnum):
    OFF = "off"
    CHECK_ONLY = "check_only"
    WALLS_FIRST_EXCESS = "walls_first_excess"
    GATE_BEFORE_TH = "gate_before_th"
    STRICT_WALLS = "strict_walls"


class KillSwitchConfig(BaseModel):
    hotkey: str = "F12"
    esc_triple: bool = True
    corner_failsafe: dict[str, Any] = Field(
        default_factory=lambda: {"enabled": True, "corner": "top_left", "hold_ms": 700}
    )


class SafetyConfig(BaseModel):
    never_spend_gems: Literal[True] = True
    ban_iap_shop: Literal[True] = True
    gem_counter_stable_frames: int = Field(default=2, ge=2, le=5)
    dry_run_default: bool = True
    mode: RunMode = RunMode.DRY_RUN
    # Limiti di sicurezza: None = illimitato (default deciso dall'utente: nessun limite
    # se non impostato a mano dalla GUI del bot). Se impostati devono essere positivi.
    max_session_hours: float | None = Field(default=None, gt=0, le=24)
    max_attacks_per_hour: int | None = Field(default=None, ge=1, le=120)
    max_upgrades_per_hour: int | None = Field(default=None, ge=1, le=30)
    # Auto-stop: quando non c'e' piu' nulla da fare (mura max + builder tutti occupati +
    # depositi pieni) il bot si ferma da solo.
    auto_stop_when_nothing_to_do: bool = True
    night_pause: dict[str, Any] = Field(default_factory=dict)
    kill_switch: KillSwitchConfig = Field(default_factory=KillSwitchConfig)
    panic_on: list[str] = Field(default_factory=list)

    @field_validator("never_spend_gems", "ban_iap_shop")
    @classmethod
    def _must_be_true(cls, value: Literal[True]) -> Literal[True]:
        if value is not True:  # pragma: no cover - difesa in profondita'
            raise ValueError("vincolo di sicurezza obbligatorio: non puo' essere disabilitato")
        return value


class DeviceConfig(BaseModel):
    backend: Literal["window", "adb"] = "window"
    window: dict[str, Any] = Field(default_factory=dict)
    adb: dict[str, Any] = Field(default_factory=dict)


class UIConfig(BaseModel):
    profile: str = "ui-2026.10"
    canonical_size: tuple[int, int] = (1920, 1080)
    locale: Literal["en", "it"] = "en"
    fail_on_fingerprint_mismatch: bool = True

    @field_validator("canonical_size")
    @classmethod
    def _check_16_9(cls, value: tuple[int, int]) -> tuple[int, int]:
        w, h = value
        if abs(w / h - 16 / 9) > 0.01:
            raise ValueError("la dimensione canonica deve essere 16:9")
        return value


class CaptureConfig(BaseModel):
    backend: Literal["wgc", "dxgi", "mss", "adb"] = "wgc"
    target_fps: int = Field(default=10, ge=1, le=60)
    black_frame_luma_threshold: float = Field(default=8.0, ge=0)
    stale_frame_timeout_s: float = Field(default=2.0, gt=0)
    save_dir: str = "out/captures"


class InputConfig(BaseModel):
    # winmsg = messaggi Win32 alla finestra: nessun focus, nessun cursore (default, zero interferenza)
    backend: Literal["winmsg", "sendinput", "adb"] = "winmsg"
    jitter_ms: tuple[int, int] = (60, 220)
    restore_cursor: bool = True

    @field_validator("jitter_ms")
    @classmethod
    def _jitter_order(cls, value: tuple[int, int]) -> tuple[int, int]:
        lo, hi = value
        if lo < 0 or hi < lo:
            raise ValueError("jitter_ms deve essere (min, max) con 0 <= min <= max")
        return value


class GuiConfig(BaseModel):
    """Preferenze dell'interfaccia (GUI minimale: start/stop + hotkey globale)."""

    language: str = "it"
    theme: str = "dark"
    debug_overlay: bool = True
    # hotkey globale start/stop: Ctrl+Alt+L (Ctrl+L "nudo" ruberebbe la scorciatoia ai browser)
    hotkey_start_stop: str = "ctrl+alt+l"
    # kill switch: Ctrl+Alt+K (F12 risulta occupato da un'altra app su questo PC)
    hotkey_kill: str = "ctrl+alt+k"


class LootThresholds(BaseModel):
    gold_min: int = Field(default=350_000, ge=0)
    elixir_min: int = Field(default=350_000, ge=0)
    dark_min: int = Field(default=2_000, ge=0)
    score_min: float = Field(default=800_000.0, ge=0)


class EarlyExitConfig(BaseModel):
    enabled: bool = True
    loot_target: dict[str, int] = Field(
        default_factory=lambda: {"gold": 250_000, "elixir": 250_000, "dark": 1_500}
    )
    max_battle_duration_s: int = Field(default=90, ge=10, le=300)
    exit_when_army_exhausted: bool = True


class AttackConfig(BaseModel):
    strategy: str = "dragon_spam"
    early_exit: EarlyExitConfig = Field(default_factory=EarlyExitConfig)
    max_battle_duration_s: int = Field(default=180, ge=30, le=300)
    retry_on_error: int = Field(default=2, ge=0, le=5)


class LootConfig(BaseModel):
    thresholds: LootThresholds = Field(default_factory=LootThresholds)
    weights: dict[str, float] = Field(default_factory=lambda: {"gold": 1.0, "elixir": 1.0, "dark": 100.0})
    max_skip_per_attack: int = Field(default=40, ge=0, le=200)
    skip_timeout_s: int = Field(default=120, ge=10)
    max_th_delta: int = Field(default=1, ge=0, le=5)
    skip_if_unreadable: bool = True


class UpgradeConfig(BaseModel):
    enabled: bool = True
    preset: str = "balanced_th18"
    queue: list[dict[str, Any]] = Field(default_factory=list)
    # ordine di priorita' delle categorie per il planner (prima = piu' importante)
    priority: list[str] = Field(
        default_factory=lambda: ["heroes", "army", "defense", "resources", "walls", "other"]
    )
    reserves: dict[str, int] = Field(
        default_factory=lambda: {"gold": 200_000, "elixir": 200_000, "dark": 3_000}
    )
    max_upgrades_per_cycle: int = Field(default=3, ge=1, le=10)
    use_lab: bool = True
    use_heroes: bool = True
    # le mura restano escluse dalla v1 dell'engine (flusso wall upgrader non ancora validato)
    include_walls: bool = False
    # dry-run: il planner legge la lista e stampa il piano, l'executor non preme CONFIRM
    dry_run: bool = True
    ignore_categories: list[str] = Field(default_factory=list)
    verify_after_upgrade: bool = True
    max_scan_scrolls: int = Field(default=45, ge=5, le=80)


class WallsConfig(BaseModel):
    mode: WallMode = WallMode.CHECK_ONLY
    check_before_upgrades: bool = True
    wall_upgrader_flow: bool = True
    max_wall_batches_per_cycle: int = Field(default=3, ge=0, le=20)
    reserve_for_buildings: dict[str, int] = Field(
        default_factory=lambda: {"gold": 100_000, "elixir": 100_000}
    )
    # Preset A (default): un builder resta sempre libero, riservato alle mura (le mura
    # richiedono un builder libero ma l'upgrade e' istantaneo). Gli altri builder lavorano.
    reserve_builder_for_walls: bool = True
    # Passaggio automatico preset A -> B: quando tutte le mura sono al massimo non serve
    # piu' tenere un builder libero, quindi tutti i builder possono lavorare.
    switch_to_all_builders_when_walls_max: bool = True
    # Auto-stop coerente: non fermarsi mai mentre le mura non sono al massimo.
    auto_stop_when_walls_max: bool = True


class HumanizeConfig(BaseModel):
    """Humanization/anti-ban: ritmi variabili, pause, tap a vuoto sicuri.

    Nota: riduce solo alcuni segnali comportamentali, NON garantisce l'immunità dal ban.
    """

    enabled: bool = True
    action_delay_ms: tuple[int, int] = (350, 1200)
    min_seconds_between_actions: float = Field(default=0.25, ge=0, le=10)
    break_probability: float = Field(default=0.02, ge=0, le=0.5)
    break_duration_s: tuple[int, int] = (8, 45)
    long_break_every_min: int = Field(default=25, ge=5, le=240)
    long_break_duration_s: tuple[int, int] = (60, 180)
    idle_tap_probability: float = Field(default=0.05, ge=0, le=0.3)
    max_actions_per_minute: int = Field(default=30, ge=1, le=120)
    max_same_target_repeats: int = Field(default=8, ge=2, le=50)

    @field_validator("action_delay_ms", "break_duration_s", "long_break_duration_s")
    @classmethod
    def _range_order(cls, value: tuple[int, int]) -> tuple[int, int]:
        lo, hi = value
        if lo < 0 or hi < lo:
            raise ValueError("intervallo deve essere (min, max) con 0 <= min <= max")
        return value


class Config(BaseModel):
    schema_version: int = 1
    profile_name: str = "default"
    device: DeviceConfig = Field(default_factory=DeviceConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    capture: CaptureConfig = Field(default_factory=CaptureConfig)
    input: InputConfig = Field(default_factory=InputConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    army: dict[str, Any] = Field(default_factory=dict)
    attack: AttackConfig = Field(default_factory=AttackConfig)
    loot: LootConfig = Field(default_factory=LootConfig)
    upgrade: UpgradeConfig = Field(default_factory=UpgradeConfig)
    walls: WallsConfig = Field(default_factory=WallsConfig)
    scheduler: dict[str, Any] = Field(default_factory=dict)
    humanize: HumanizeConfig = Field(default_factory=HumanizeConfig)
    telemetry: dict[str, Any] = Field(default_factory=dict)
    gui: GuiConfig = Field(default_factory=GuiConfig)


__all__ = [
    "AttackConfig",
    "CaptureConfig",
    "Config",
    "DeviceConfig",
    "EarlyExitConfig",
    "GuiConfig",
    "HumanizeConfig",
    "InputConfig",
    "KillSwitchConfig",
    "LootConfig",
    "LootThresholds",
    "RunMode",
    "SafetyConfig",
    "UIConfig",
    "UpgradeConfig",
    "WallMode",
    "WallsConfig",
]
