"""Adapter 註冊機制：裝飾器自註冊 + 掃描觸發。

設計原因：`app.adapters` 套件下會陸續長出多個具體來源模組（日價量、籌碼、分點、除權息…），
若在某處手寫「來源清單」，清單永遠會跟實際存在的 adapter 脫鉤——加了新 adapter 忘記登記、
或本任務完成時具體 adapter 都還不存在，清單就會是空的或錯的。

改用兩段式機制：

1. **`@register`**：各 adapter 模組在自己檔案內，於定義 `DataSource` 子類別時標註它，
   由子類別自己宣告「我是一個來源」，不假手他人維護清單。
2. **`discover()`**：用 `pkgutil.iter_modules` 掃描 `app.adapters` 套件底下的模組並逐一
   `importlib.import_module`——單純 import 該模組就會執行其中的 `@register`，
   不需要知道模組裡有什麼類別、叫什麼名字。

`discover()` 在具體 adapter 尚未存在時掃到零個來源，是正確結果，不是錯誤。
"""

from __future__ import annotations

import importlib
import pkgutil

from app.adapters.base import DataSource

# 套件內部視為基礎設施、不是具體來源的模組名稱，discover() 掃描時略過。
_INFRASTRUCTURE_MODULES = frozenset({"base", "registry"})

_registry: dict[str, type[DataSource]] = {}


def register(name_or_cls: str | type[DataSource] | None = None):
    """類別裝飾器，把 `DataSource` 子類別以來源名稱註冊進 registry。

    兩種用法皆可：

        @register
        class DailyPriceSource(DataSource): ...

        @register("daily_price")
        class DailyPriceSource(DataSource): ...

    裸用時以類別名稱（`cls.__name__`）作為註冊名稱；帶字串時用該字串。
    同一名稱重複註冊到不同類別會拋錯，避免兩個來源互相覆蓋而不自知。
    """

    def _apply(cls: type[DataSource], name: str) -> type[DataSource]:
        if not (isinstance(cls, type) and issubclass(cls, DataSource)):
            raise TypeError(f"@register 只能套用於 DataSource 子類別，收到 {cls!r}")
        existing = _registry.get(name)
        if existing is not None and existing is not cls:
            raise ValueError(
                f"來源名稱 '{name}' 已被 {existing!r} 註冊，不可重複註冊給 {cls!r}"
            )
        _registry[name] = cls
        return cls

    if isinstance(name_or_cls, type):
        # 裸用：@register（沒有呼叫、直接把類別傳進來）
        return _apply(name_or_cls, name_or_cls.__name__)

    def _decorator(cls: type[DataSource]) -> type[DataSource]:
        return _apply(cls, name_or_cls or cls.__name__)

    return _decorator


def discover() -> dict[str, type[DataSource]]:
    """掃描 `app.adapters` 套件底下的模組並逐一 import，觸發各模組內的 `@register`。

    回傳目前已註冊來源的淺拷貝（key 為註冊名稱，value 為 `DataSource` 子類別）。
    具體 adapter 尚未存在時回傳空 dict，這是正確結果而非錯誤。
    """
    package = importlib.import_module("app.adapters")
    for module_info in pkgutil.iter_modules(package.__path__, prefix=f"{package.__name__}."):
        module_name = module_info.name.rsplit(".", 1)[-1]
        if module_name in _INFRASTRUCTURE_MODULES:
            continue
        importlib.import_module(module_info.name)
    return dict(_registry)


def registered_sources() -> dict[str, type[DataSource]]:
    """列舉目前已註冊的來源，不觸發掃描。供只想查詢現況、不需要順便 import 新模組的呼叫端使用。"""
    return dict(_registry)
