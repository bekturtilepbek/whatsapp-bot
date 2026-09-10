"""Storage-зависимость для api (FEATURES.md 6.8, загрузка фото товара).

Ленивая инициализация — тот же принцип, что и SessionDep (api/db.py): не
создавать клиента на импорте модуля, чтобы тесты могли подменить
зависимость через dependency_overrides до первого реального использования.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from integrations.storage import Storage, create_storage

_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = create_storage()
    return _storage


StorageDep = Annotated[Storage, Depends(get_storage)]
