import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


class VoiceRoutingTest(unittest.TestCase):
    _voice_assistant = None

    def _import_voice_assistant(self):
        if self.__class__._voice_assistant is not None:
            return self.__class__._voice_assistant

        fake_numpy = types.SimpleNamespace()
        fake_sounddevice = types.SimpleNamespace(InputStream=object)
        fake_genai = types.SimpleNamespace(configure=lambda **_: None)
        fake_whisper = types.SimpleNamespace(load_model=lambda *_args, **_kwargs: object())
        fake_pygame = types.SimpleNamespace(
            mixer=types.SimpleNamespace(
                init=lambda: None,
                music=types.SimpleNamespace(
                    load=lambda *_args, **_kwargs: None,
                    play=lambda: None,
                    get_busy=lambda: False,
                    stop=lambda: None,
                    unload=lambda: None,
                ),
            )
        )
        fake_scipy = types.ModuleType("scipy")
        fake_scipy_io = types.ModuleType("scipy.io")
        fake_scipy_wavfile = types.SimpleNamespace(write=lambda *_args, **_kwargs: None)

        modules = {
            "faster_whisper": None,
            "numpy": fake_numpy,
            "sounddevice": fake_sounddevice,
            "google.generativeai": fake_genai,
            "whisper": fake_whisper,
            "pygame": fake_pygame,
            "scipy": fake_scipy,
            "scipy.io": fake_scipy_io,
            "scipy.io.wavfile": fake_scipy_wavfile,
        }
        sys.modules.pop("voice_assistant", None)
        with patch.dict(sys.modules, modules):
            self.__class__._voice_assistant = importlib.import_module("voice_assistant")
        return self.__class__._voice_assistant

    def test_high_priority_tasks_route_directly_to_list_tasks(self):
        voice_assistant = self._import_voice_assistant()
        self.assertEqual(
            voice_assistant._direct_tool_for_text("list my high priority tasks"),
            ("list_tasks", {"priority": "high", "limit": 8}),
        )

    def test_empty_gemini_stop_is_not_spoken_as_reply(self):
        voice_assistant = self._import_voice_assistant()
        reason = types.SimpleNamespace(name="STOP", value=1)
        response = types.SimpleNamespace(
            candidates=[
                types.SimpleNamespace(
                    finish_reason=reason,
                    content=types.SimpleNamespace(parts=[]),
                )
            ]
        )

        self.assertEqual(voice_assistant._response_text(response), "")
        self.assertEqual(voice_assistant._empty_response_detail(response), "finish reason: STOP (1)")

    def test_empty_gemini_response_retries_for_spoken_text(self):
        voice_assistant = self._import_voice_assistant()
        empty_response = types.SimpleNamespace(candidates=[], parts=[])
        retry_response = types.SimpleNamespace(text=" Sure, I'm here.")
        chat = MagicMock()
        chat.send_message.return_value = retry_response

        reply = voice_assistant._retry_empty_spoken_response(chat, empty_response)

        self.assertEqual(reply, "Sure, I'm here.")
        chat.send_message.assert_called_once()


if __name__ == "__main__":
    unittest.main()
