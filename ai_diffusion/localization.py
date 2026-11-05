import json
from pathlib import Path
from typing import NamedTuple

from .util import client_logger as log
from .util import user_data_dir

_language_dir = Path(__file__).parent / "language"


def language_for_locale(locale: str, available: set[str]) -> str:
    """The catalog id for a BCP 47 locale (``"ja-JP"``, ``"pt-BR"``, ``"zh-Hant"``), or ``"en"``
    when no catalog fits."""
    tag = locale.strip().lower().replace("_", "-")
    lang, _sep, region = tag.partition("-")
    candidates = [tag]
    if lang == "zh":
        traditional = any(part in ("hant", "tw", "hk", "mo") for part in tag.split("-")[1:])
        candidates.append("zh-tw" if traditional else "zh-cn")
    elif lang == "ca":
        candidates.append("es-ca")  # Catalan (Valencian)
    candidates.extend((f"{lang}-{region}" if region else lang, lang))
    candidates += sorted(id for id in available if id.startswith(f"{lang}-"))
    return next((id for id in candidates if id in available), "en")


def default_language() -> str:
    """The language used while the user hasn't picked one: in PhotoCraft, the host's UI language
    when there is a catalog for it (REQ-34.0.2); otherwise, and in Krita, English."""
    import krita

    photocraft_host = getattr(krita, "photocraft_host", None)
    host = photocraft_host() if photocraft_host is not None else None
    if host is None:
        return "en"
    available = {f.stem for f in _language_dir.iterdir() if f.suffix == ".json"}
    return language_for_locale(host.locale, available)


class Language(NamedTuple):
    id: str
    name: str
    path: Path

    @staticmethod
    def from_file(filepath: Path):
        try:
            with filepath.open(encoding="utf-8") as f:
                lang = json.load(f)
                return Language(lang["id"], lang["name"], filepath)
        except Exception as e:
            log.warning(f"Not a valid language file: {filepath}: {e}")
            return None


class Localization:
    _id: str
    _name: str
    _translations: dict[str, str]

    available: list[Language]
    current: "Localization"

    def __init__(self, id: str = "en", name: str = "English", translations: dict | None = None):
        if translations is None:
            translations = {}
        self._id = id
        self._name = name
        self._translations = translations

    def translate(self, key: str, **kwargs):
        translation = self._translations.get(key, key) or key
        if kwargs:
            try:
                translation = translation.format(**kwargs)
            except Exception as e:
                log.error(f"Failed to format translation for {key}: {e}")
                translation = key.format(**kwargs)
        return translation

    @property
    def id(self):
        return self._id

    @staticmethod
    def load(id: str, filepath: Path):
        try:
            with filepath.open(encoding="utf-8") as f:
                lang = json.load(f)
                return Localization(id, lang["name"], lang["translations"])
        except Exception as e:
            raise RuntimeError(f"Could not load language file for {id} at {filepath}: {e}")

    @staticmethod
    def init(settings_path: Path | None = None):
        language = default_language()
        settings_path = settings_path or user_data_dir / "settings.json"
        if settings_path.exists():
            try:
                with settings_path.open(encoding="utf-8") as f:
                    settings = json.load(f)
                    language = settings.get("language", language)
            except Exception as e:
                log.warning(f"Could not read language settings: {e}")

        language_file = Path(__file__).parent / "language" / f"{language}.json"
        try:
            return Localization.load(language, language_file)
        except Exception as e:
            log.warning(str(e))
            return Localization()

    @staticmethod
    def scan():
        dir = Path(__file__).parent / "language"
        langs = (Language.from_file(f) for f in dir.iterdir() if f.suffix == ".json")
        return [lang for lang in langs if lang]


Localization.current = Localization.init()
Localization.available = Localization.scan()


def translate(key: str, **kwargs):
    return Localization.current.translate(key, **kwargs)
