"""Classificazione dello stato dello schermo di gioco.

Il classificatore e' volutamente **conservativo**: se non riconosce lo stato restituisce
``UNKNOWN`` e il bot deve mettersi in pausa/recuperare, mai tappare alla cieca.

Stati riconosciuti oggi (verificati su frame reali):
- ``HOME``: villaggio principale, nessun pannello/menu aperto;
- ``BUILD_MENU``: menu "Buildings & Heroes" (pannello a destra + X in alto a destra);
- ``UPGRADE_CONFIRM``: dialogo "Upgrade <X> to Level <N>?" con X centrale;
- ``PLACEMENT``: modalita' piazzamento nuovo edificio (X rossa + spunta al centro);
- ``NETWORK_ERROR``: modal di disconnessione per inattivita' ("Anyone there?").

Stati pianificati ma non ancora implementati (restano ``UNKNOWN``): battaglia, menu
battaglia, popup, negozio, Hero Hall, wall upgrader.
"""
from __future__ import annotations

import numpy as np

from cocbot.core.types import ScreenState
from cocbot.vision import ui
from cocbot.vision.safe_tap import looks_like_home, panel_likely_open


def classify(image: np.ndarray) -> ScreenState:
    """Classifica lo stato dello schermo dal frame (senza input)."""
    if image is None or image.ndim != 3 or image.size == 0:
        return ScreenState.UNKNOWN
    if image.shape[0] < 240 or image.shape[1] < 400:
        return ScreenState.UNKNOWN

    # ordine importante: il dialogo ha anche la X del menu dietro di se'
    if ui.find_dialog_close(image) is not None:
        return ScreenState.UPGRADE_CONFIRM
    if ui.find_inactivity_modal(image) is not None:
        return ScreenState.NETWORK_ERROR
    if ui.find_placement_exit(image) is not None:
        return ScreenState.PLACEMENT
    if _is_build_menu(image):
        return ScreenState.BUILD_MENU
    if looks_like_home(image) and not panel_likely_open(image):
        return ScreenState.HOME
    return ScreenState.UNKNOWN


def _is_build_menu(image: np.ndarray) -> bool:
    if ui.find_build_panel(image) is None:
        return False
    return ui.find_menu_close(image) is not None


def describe(state: ScreenState) -> str:
    """Descrizione italiana dello stato (per log/CLI)."""
    descriptions = {
        ScreenState.HOME: "home village",
        ScreenState.BUILD_MENU: "menu Build (Buildings & Heroes)",
        ScreenState.UPGRADE_CONFIRM: "dialogo conferma upgrade",
        ScreenState.PLACEMENT: "piazzamento nuovo edificio",
        ScreenState.NETWORK_ERROR: "disconnessione per inattivita' (serve RELOAD GAME)",
        ScreenState.UNKNOWN: "stato sconosciuto",
    }
    return descriptions.get(state, state.value)


__all__ = ["classify", "describe"]
