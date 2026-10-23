"""Erreurs d'import.

Chaque erreur porte un code court et stable (ex. « encrypted_pdf ») : l'interface
le traduit en un message clair pour l'utilisateur, en français ou en anglais.
"""

from pathlib import Path
from typing import Literal

ImportErrorCode = Literal[
    "file_not_found",      # le fichier n'existe pas
    "unsupported_format",  # extension non prise en charge
    "unreadable_file",     # fichier abîmé ou qui n'est pas ce que dit son extension
    "encrypted_pdf",       # PDF protégé par un mot de passe
    "empty_document",      # aucune page (ou aucune page non vide)
]


class ScoreImportError(Exception):
    """Une partition n'a pas pu être importée."""

    def __init__(self, code: ImportErrorCode, path: Path | str, detail: str = "") -> None:
        self.code = code
        self.path = str(path)
        self.detail = detail
        super().__init__(f"{code}: {path}" + (f" ({detail})" if detail else ""))
