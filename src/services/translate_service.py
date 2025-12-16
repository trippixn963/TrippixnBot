"""
TrippixnBot - Translation Service
=================================

Translation service using Google Translate.

Author: حَـــــنَّـــــا
"""

import asyncio
from dataclasses import dataclass
from typing import Optional
from deep_translator import GoogleTranslator
from langdetect import detect, LangDetectException

from src.core import log


# =============================================================================
# Language Data
# =============================================================================

# Common language codes and their display names + flag emojis
LANGUAGES = {
    "ar": ("Arabic", "🇸🇦"),
    "en": ("English", "🇺🇸"),
    "es": ("Spanish", "🇪🇸"),
    "fr": ("French", "🇫🇷"),
    "de": ("German", "🇩🇪"),
    "it": ("Italian", "🇮🇹"),
    "pt": ("Portuguese", "🇵🇹"),
    "ru": ("Russian", "🇷🇺"),
    "zh-CN": ("Chinese", "🇨🇳"),
    "ja": ("Japanese", "🇯🇵"),
    "ko": ("Korean", "🇰🇷"),
    "tr": ("Turkish", "🇹🇷"),
    "nl": ("Dutch", "🇳🇱"),
    "pl": ("Polish", "🇵🇱"),
    "uk": ("Ukrainian", "🇺🇦"),
    "hi": ("Hindi", "🇮🇳"),
    "he": ("Hebrew", "🇮🇱"),
    "fa": ("Persian", "🇮🇷"),
    "ur": ("Urdu", "🇵🇰"),
    "sv": ("Swedish", "🇸🇪"),
    "da": ("Danish", "🇩🇰"),
    "no": ("Norwegian", "🇳🇴"),
    "fi": ("Finnish", "🇫🇮"),
    "el": ("Greek", "🇬🇷"),
    "cs": ("Czech", "🇨🇿"),
    "ro": ("Romanian", "🇷🇴"),
    "hu": ("Hungarian", "🇭🇺"),
    "th": ("Thai", "🇹🇭"),
    "vi": ("Vietnamese", "🇻🇳"),
    "id": ("Indonesian", "🇮🇩"),
    "ms": ("Malay", "🇲🇾"),
}

# Language aliases for easier input
LANGUAGE_ALIASES = {
    "arabic": "ar",
    "english": "en",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "portuguese": "pt",
    "russian": "ru",
    "chinese": "zh-CN",
    "japanese": "ja",
    "korean": "ko",
    "turkish": "tr",
    "dutch": "nl",
    "polish": "pl",
    "ukrainian": "uk",
    "hindi": "hi",
    "hebrew": "he",
    "persian": "fa",
    "farsi": "fa",
    "urdu": "ur",
    "swedish": "sv",
    "danish": "da",
    "norwegian": "no",
    "finnish": "fi",
    "greek": "el",
    "czech": "cs",
    "romanian": "ro",
    "hungarian": "hu",
    "thai": "th",
    "vietnamese": "vi",
    "indonesian": "id",
    "malay": "ms",
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class TranslationResult:
    """Result of a translation operation."""
    success: bool
    original_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    source_name: str
    target_name: str
    source_flag: str
    target_flag: str
    error: Optional[str] = None


# =============================================================================
# Translation Service
# =============================================================================

class TranslateService:
    """Service for translating text."""

    def __init__(self):
        log.success("Translation Service initialized")

    def resolve_language(self, lang_input: str) -> Optional[str]:
        """
        Resolve a language input to a language code.

        Args:
            lang_input: Language code or name (e.g., "ar", "arabic", "Arabic")

        Returns:
            Language code or None if not found
        """
        lang_input = lang_input.strip()
        lang_lower = lang_input.lower()

        # Direct code match (case-sensitive first)
        if lang_input in LANGUAGES:
            return lang_input

        # Case-insensitive code match
        for code in LANGUAGES:
            if code.lower() == lang_lower:
                return code

        # Alias match (always lowercase)
        if lang_lower in LANGUAGE_ALIASES:
            return LANGUAGE_ALIASES[lang_lower]

        return None

    def get_language_info(self, lang_code: str) -> tuple[str, str]:
        """Get language name and flag for a code."""
        if lang_code in LANGUAGES:
            return LANGUAGES[lang_code]
        # Handle unknown but valid codes
        return (lang_code.upper(), "🌐")

    def detect_language(self, text: str) -> Optional[str]:
        """
        Detect the language of text.

        Args:
            text: Text to detect language of

        Returns:
            Language code or None if detection failed
        """
        try:
            detected = detect(text)
            # langdetect returns 'zh-cn' but we use 'zh-CN'
            if detected == "zh-cn":
                return "zh-CN"
            return detected
        except LangDetectException:
            return None

    async def translate(
        self,
        text: str,
        target_lang: str = "en",
        source_lang: str = "auto"
    ) -> TranslationResult:
        """
        Translate text to target language.

        Args:
            text: Text to translate
            target_lang: Target language code (default: English)
            source_lang: Source language code (default: auto-detect)

        Returns:
            TranslationResult with translation details
        """
        # Resolve target language
        resolved_target = self.resolve_language(target_lang)
        if not resolved_target:
            return TranslationResult(
                success=False,
                original_text=text,
                translated_text="",
                source_lang="",
                target_lang=target_lang,
                source_name="",
                target_name="",
                source_flag="",
                target_flag="",
                error=f"Unknown language: {target_lang}"
            )

        # Detect source language if auto
        if source_lang == "auto":
            detected = self.detect_language(text)
            source_lang = detected or "auto"

        log.tree("Translating", [
            ("Text", text[:50] + "..." if len(text) > 50 else text),
            ("From", source_lang),
            ("To", resolved_target),
        ], emoji="🌐")

        try:
            # Run translation in thread pool (deep_translator is sync)
            loop = asyncio.get_event_loop()
            translator = GoogleTranslator(source=source_lang, target=resolved_target)
            translated = await loop.run_in_executor(None, translator.translate, text)

            # Get language info
            source_name, source_flag = self.get_language_info(source_lang)
            target_name, target_flag = self.get_language_info(resolved_target)

            log.tree("Translation Complete", [
                ("From", f"{source_name} {source_flag}"),
                ("To", f"{target_name} {target_flag}"),
                ("Result Length", len(translated)),
            ], emoji="✅")

            return TranslationResult(
                success=True,
                original_text=text,
                translated_text=translated,
                source_lang=source_lang,
                target_lang=resolved_target,
                source_name=source_name,
                target_name=target_name,
                source_flag=source_flag,
                target_flag=target_flag,
            )

        except Exception as e:
            log.error("Translation Failed", [
                ("Error", type(e).__name__),
                ("Message", str(e)),
            ])

            return TranslationResult(
                success=False,
                original_text=text,
                translated_text="",
                source_lang=source_lang,
                target_lang=resolved_target,
                source_name="",
                target_name="",
                source_flag="",
                target_flag="",
                error=str(e)
            )

    def get_supported_languages(self) -> list[tuple[str, str, str]]:
        """Get list of supported languages as (code, name, flag) tuples."""
        return [(code, name, flag) for code, (name, flag) in LANGUAGES.items()]


# Global instance
translate_service = TranslateService()
